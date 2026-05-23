import importlib
import json
import sys
from pathlib import Path

import pytest

from final.ai_enricher import request_json_with_retries
from final.normalizer import normalize_parser_result
from final.schema import build_final_output


def write_minimal_png(path: Path) -> None:
    path.write_bytes(
        bytes.fromhex(
            "89504E470D0A1A0A"
            "0000000D4948445200000001000000010802000000907753DE"
            "0000000C4944415408D763F8FFFF3F0005FE02FEA7A69D6E"
            "0000000049454E44AE426082"
        )
    )


def test_final_parser_modules_are_importable():
    assert importlib.import_module("final.sinagong_pdf_parser")
    assert importlib.import_module("final.normal_pdf_parser.extract_pdf")
    assert importlib.import_module("final.normal_pdf_parser.generate_answer")
    assert importlib.import_module("final.normal_pdf_parser.batch_generate_answer")
    assert importlib.import_module("final.normal_pdf_parser.generate_concept")
    assert importlib.import_module("final.normal_pdf_parser.batch_generate_concept")
    assert importlib.import_module("final.normal_pdf_parser.extract_questions")
    assert importlib.import_module("final.text_refiner")
    assert importlib.import_module("final.image_captioner")


def test_create_openai_client_disables_sdk_retries(monkeypatch):
    from final.ai_enricher import create_openai_client

    captured = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setitem(sys.modules, "openai", type("FakeOpenAIModule", (), {"OpenAI": FakeOpenAI})())

    create_openai_client(
        base_url="https://example.ngrok-free.dev/v1",
        api_key="token",
        timeout=12.5,
    )

    assert captured == {
        "base_url": "https://example.ngrok-free.dev/v1",
        "api_key": "token",
        "timeout": 12.5,
        "max_retries": 0,
    }


def test_build_final_output_assigns_global_image_ids_and_tokens(tmp_path):
    crop1 = tmp_path / "crop1.png"
    crop2 = tmp_path / "crop2.png"
    write_minimal_png(crop1)
    write_minimal_png(crop2)
    parser_result = {
        "source": "test-1.pdf",
        "questions": [
            {
                "question_number": 1,
                "question_text": "다음 중 옳은 것은?",
                "choices": [{"number": 1, "text": "정답"}, {"number": 2, "text": "오답"}],
                "images": [{"crop_path": str(crop1)}],
            },
            {
                "question_number": 2,
                "question_text": "그림을 보고 고르시오.",
                "choices": [{"number": 1, "text": "A"}],
                "images": [{"crop_path": str(crop2)}],
            },
        ],
    }

    normalized = normalize_parser_result(parser_result, source_pdf=Path("test-1.pdf"))
    output = build_final_output(normalized, output_dir=tmp_path / "out")

    first = output["questions"][0]
    second = output["questions"][1]
    assert first["content"].endswith("[image001]")
    assert second["content"].endswith("[image002]")
    assert first["images"][0]["image_id"] == "image001"
    assert second["images"][0]["image_name"] == "image002.png"
    assert (tmp_path / "out" / "images" / "image001.png").exists()
    assert output["metadata"]["requires_answer_review"] is True


def test_schema_preserves_known_correct_answer(tmp_path):
    parser_result = {
        "source": "sample.pdf",
        "questions": [
            {
                "question_number": 7,
                "question_text": "정답은?",
                "choices": [
                    {"number": 1, "text": "A"},
                    {"number": 2, "text": "B", "is_correct": True},
                ],
                "images": [],
            }
        ],
    }

    normalized = normalize_parser_result(parser_result, source_pdf=Path("sample.pdf"))
    output = build_final_output(normalized, output_dir=tmp_path)

    options = output["questions"][0]["options"]
    assert [option["is_correct"] for option in options] == [False, True]
    assert output["metadata"]["requires_answer_review"] is False


def test_ai_json_request_retries_invalid_json_then_succeeds():
    class FakeCompletions:
        def __init__(self):
            self.calls = 0

        def create(self, **kwargs):
            self.calls += 1
            content = "not-json" if self.calls == 1 else '{"ok": true}'
            message = type("Message", (), {"content": content})()
            choice = type("Choice", (), {"message": message})()
            return type("Response", (), {"choices": [choice]})()

    class FakeClient:
        def __init__(self):
            self.chat = type("Chat", (), {"completions": FakeCompletions()})()

    payload = request_json_with_retries(
        client=FakeClient(),
        model="local-model",
        messages=[{"role": "user", "content": "JSON"}],
        max_retries=2,
    )

    assert payload == {"ok": True}


def test_ai_json_request_retries_request_exceptions_then_succeeds():
    class FakeCompletions:
        def __init__(self):
            self.calls = 0

        def create(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise TimeoutError("Request timed out.")
            message = type("Message", (), {"content": '{"ok": true}'})()
            choice = type("Choice", (), {"message": message})()
            return type("Response", (), {"choices": [choice]})()

    class FakeClient:
        def __init__(self):
            self.completions = FakeCompletions()
            self.chat = type("Chat", (), {"completions": self.completions})()

    client = FakeClient()
    payload = request_json_with_retries(
        client=client,
        model="local-model",
        messages=[{"role": "user", "content": "JSON"}],
        max_retries=2,
    )

    assert payload == {"ok": True}
    assert client.completions.calls == 2


def test_ai_json_request_error_includes_response_preview():
    class FakeCompletions:
        def create(self, **kwargs):
            message = type("Message", (), {"content": '{"content": "unterminated'})()
            choice = type("Choice", (), {"message": message})()
            return type("Response", (), {"choices": [choice]})()

    class FakeClient:
        def __init__(self):
            self.chat = type("Chat", (), {"completions": FakeCompletions()})()

    with pytest.raises(RuntimeError) as exc_info:
        request_json_with_retries(
            client=FakeClient(),
            model="local-model",
            messages=[{"role": "user", "content": "JSON"}],
            max_retries=1,
        )

    message = str(exc_info.value)
    assert "응답 원문 preview" in message
    assert '{"content": "unterminated' in message


def test_ai_json_request_raises_last_request_exception_after_retries():
    class FakeCompletions:
        def __init__(self):
            self.calls = 0

        def create(self, **kwargs):
            self.calls += 1
            raise TimeoutError(f"Request timed out {self.calls}")

    class FakeClient:
        def __init__(self):
            self.completions = FakeCompletions()
            self.chat = type("Chat", (), {"completions": self.completions})()

    client = FakeClient()
    with pytest.raises(TimeoutError, match="timed out 2"):
        request_json_with_retries(
            client=client,
            model="local-model",
            messages=[{"role": "user", "content": "JSON"}],
            max_retries=2,
        )

    assert client.completions.calls == 2


def test_image_captioner_sends_problem_context_and_image_url(tmp_path):
    from final.image_captioner import caption_image

    image_path = tmp_path / "image001.png"
    write_minimal_png(image_path)

    class FakeCompletions:
        def __init__(self):
            self.calls = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            message = type(
                "Message",
                (),
                {
                    "content": json.dumps(
                        {"image_caption": "E-R 다이어그램 그림"},
                        ensure_ascii=False,
                    )
                },
            )()
            choice = type("Choice", (), {"message": message})()
            return type("Response", (), {"choices": [choice]})()

    class FakeClient:
        def __init__(self):
            self.completions = FakeCompletions()
            self.chat = type("Chat", (), {"completions": self.completions})()

    question = {
        "content": "다음 E-R 다이어그램을 보고 옳은 것을 고르시오. [image001]",
        "question_source": "sample.pdf 1번 문제",
        "images": [{"image_id": "image001", "image_name": "image001.png", "image_caption": ""}],
        "options": [{"order": 1, "content": "개체와 관계를 표현한다."}],
    }
    image = question["images"][0]
    client = FakeClient()

    caption = caption_image(
        client=client,
        model="local-model",
        question=question,
        image=image,
        image_path=image_path,
        max_retries=1,
    )

    message_content = client.completions.calls[0]["messages"][0]["content"]
    assert caption == "E-R 다이어그램 그림"
    assert image["image_caption"] == "E-R 다이어그램 그림"
    assert message_content[0]["type"] == "text"
    assert "다음 E-R 다이어그램" in message_content[0]["text"]
    assert "개체와 관계를 표현한다." in message_content[0]["text"]
    assert message_content[1]["type"] == "image_url"
    assert message_content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_ai_enricher_does_not_update_image_caption():
    from final.ai_enricher import enrich_question

    class FakeCompletions:
        def __init__(self):
            self.prompt = ""

        def create(self, **kwargs):
            self.prompt = kwargs["messages"][0]["content"]
            payload = {
                "image_captions": {"image001": "새 caption"},
                "hint_explanation": "힌트",
                "option_explanations": {"1": "선지 해설"},
                "correct_orders": [1],
            }
            message = type(
                "Message",
                (),
                {"content": json.dumps(payload, ensure_ascii=False)},
            )()
            choice = type("Choice", (), {"message": message})()
            return type("Response", (), {"choices": [choice]})()

    class FakeClient:
        def __init__(self):
            self.completions = FakeCompletions()
            self.chat = type("Chat", (), {"completions": self.completions})()

    question = {
        "content": "문제 [image001]",
        "images": [
            {
                "image_id": "image001",
                "image_name": "image001.png",
                "image_caption": "기존 caption",
            }
        ],
        "hint_explanation": "",
        "options": [
            {
                "order": 1,
                "is_correct": False,
                "content": "선지",
                "images": [],
                "option_explanation": "",
            }
        ],
    }
    client = FakeClient()

    enrich_question(client=client, model="local-model", question=question, max_retries=1)

    assert "image_captions" not in client.completions.prompt
    assert question["images"][0]["image_caption"] == "기존 caption"
    assert question["hint_explanation"] == "힌트"
    assert question["options"][0]["option_explanation"] == "선지 해설"
    assert question["options"][0]["is_correct"] is True


def test_parse_pdf_uses_selected_normal_parser_without_fallback(monkeypatch, tmp_path):
    from final import parse_pdf

    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    def fail_sinagong(*args, **kwargs):
        raise RuntimeError("unsupported")

    def result_success(*args, **kwargs):
        return {
            "source": "sample.pdf",
            "questions": [
                {
                    "question_number": 1,
                    "question_text": "문제",
                    "choices": [{"number": 1, "text": "선지"}],
                    "images": [],
                }
            ],
        }

    monkeypatch.setattr(parse_pdf, "run_sinagong_parser", fail_sinagong)
    monkeypatch.setattr(parse_pdf, "run_normal_parser", result_success)

    output_path = parse_pdf.run_pipeline(
        pdf_path=pdf_path,
        output_dir=tmp_path / "out",
        parser_name="normal",
        dpi=72,
        ai_base_url=None,
        model="local-model",
        max_retries=1,
    )

    saved = json.loads(output_path.read_text(encoding="utf-8"))
    assert saved["questions"][0]["content"] == "문제"


def test_run_pipeline_generates_image_captions_before_ai_enrichment(monkeypatch, tmp_path):
    from final import parse_pdf

    pdf_path = tmp_path / "sample.pdf"
    crop_path = tmp_path / "crop.png"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    write_minimal_png(crop_path)

    def fake_parse_with_selected_parser(**kwargs):
        return {
            "source": "sample.pdf",
            "questions": [
                {
                    "question_number": 1,
                    "question_text": "그림을 보고 고르시오.",
                    "choices": [{"number": 1, "text": "선지"}],
                    "images": [{"crop_path": str(crop_path)}],
                }
            ],
        }

    seen_by_enrichment = {}

    def fake_apply_text_refinement(**kwargs):
        return kwargs["output"]

    def fake_apply_image_captioning(**kwargs):
        kwargs["output"]["questions"][0]["images"][0]["image_caption"] = "이미지 설명"
        return kwargs["output"]

    def fake_apply_ai_enrichment(**kwargs):
        seen_by_enrichment["caption"] = kwargs["output"]["questions"][0]["images"][0][
            "image_caption"
        ]
        return kwargs["output"]

    monkeypatch.setattr(parse_pdf, "parse_with_selected_parser", fake_parse_with_selected_parser)
    monkeypatch.setattr(parse_pdf, "apply_text_refinement", fake_apply_text_refinement)
    monkeypatch.setattr(parse_pdf, "apply_image_captioning", fake_apply_image_captioning)
    monkeypatch.setattr(parse_pdf, "apply_ai_enrichment", fake_apply_ai_enrichment)

    parse_pdf.run_pipeline(
        pdf_path=pdf_path,
        output_dir=tmp_path / "out",
        parser_name="sinagong",
        dpi=72,
        ai_base_url="https://example.ngrok-free.dev/v1",
        model="local-model",
        max_retries=1,
    )

    assert seen_by_enrichment["caption"] == "이미지 설명"


def test_parse_pdf_rejects_unknown_parser(tmp_path):
    from final import parse_pdf

    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    with pytest.raises(ValueError, match="지원하지 않는 parser"):
        parse_pdf.run_pipeline(
            pdf_path=pdf_path,
            output_dir=tmp_path / "out",
            parser_name="auto",
            dpi=72,
            ai_base_url=None,
            model="local-model",
            max_retries=1,
        )


def test_parse_pdf_prompts_for_parser_when_missing(monkeypatch):
    from final import parse_pdf

    class InteractiveStdin:
        def isatty(self):
            return True

    monkeypatch.setattr(parse_pdf.sys, "stdin", InteractiveStdin())
    monkeypatch.setattr("builtins.input", lambda prompt: "normal")

    args = parse_pdf.parse_args(
        [
            "--pdf",
            "sample.pdf",
            "--output-dir",
            "out",
        ]
    )

    assert args.parser == "normal"


def test_parse_pdf_requires_parser_when_stdin_is_not_interactive(monkeypatch):
    from final import parse_pdf

    class NonInteractiveStdin:
        def isatty(self):
            return False

    monkeypatch.setattr(parse_pdf.sys, "stdin", NonInteractiveStdin())

    with pytest.raises(SystemExit):
        parse_pdf.parse_args(
            [
                "--pdf",
                "sample.pdf",
                "--output-dir",
                "out",
            ]
        )


@pytest.mark.parametrize("option", ["--ai-timeout", "--ai-max-failures"])
def test_parse_pdf_cli_no_longer_accepts_ai_failure_options(option):
    from final import parse_pdf

    with pytest.raises(SystemExit):
        parse_pdf.parse_args(
            [
                "--pdf",
                "sample.pdf",
                "--output-dir",
                "out",
                "--parser",
                "normal",
                option,
                "60",
            ]
        )


def test_ai_enrichment_failure_keeps_parser_output(monkeypatch):
    from final.parse_pdf import apply_ai_enrichment

    output = {
        "source_pdf": "sample.pdf",
        "questions": [
            {
                "content": "문제",
                "question_source": "sample.pdf 1번 문제",
                "images": [],
                "hint_explanation": "",
                "options": [
                    {
                        "order": 1,
                        "is_correct": False,
                        "content": "선지",
                        "images": [],
                        "option_explanation": "",
                    }
                ],
            }
        ],
        "metadata": {
            "total_questions": 1,
            "total_images": 0,
            "requires_answer_review": False,
        },
    }

    monkeypatch.setattr("final.parse_pdf.create_openai_client", lambda **kwargs: object())

    def fail_enrich(*args, **kwargs):
        raise RuntimeError("ngrok upstream unavailable")

    monkeypatch.setattr("final.parse_pdf.enrich_question", fail_enrich)

    enriched = apply_ai_enrichment(
        output=output,
        ai_base_url="https://example.ngrok-free.dev/v1",
        ai_api_key="token",
        model="local-model",
        max_retries=1,
    )

    assert enriched["questions"][0]["content"] == "문제"
    assert enriched["metadata"]["requires_answer_review"] is True
    assert enriched["metadata"]["ai_enrichment"]["failed_questions"] == 1


def test_ai_enrichment_stops_after_max_failures(monkeypatch):
    from final.parse_pdf import apply_ai_enrichment

    output = {
        "source_pdf": "sample.pdf",
        "questions": [
            {
                "content": f"문제 {index}",
                "question_source": f"sample.pdf {index}번 문제",
                "images": [],
                "hint_explanation": "",
                "options": [],
            }
            for index in range(1, 6)
        ],
        "metadata": {
            "total_questions": 5,
            "total_images": 0,
            "requires_answer_review": False,
        },
    }
    calls = []

    monkeypatch.setattr("final.parse_pdf.create_openai_client", lambda **kwargs: object())

    def fail_enrich(*args, **kwargs):
        calls.append(kwargs["question"]["question_source"])
        raise RuntimeError("connection error")

    monkeypatch.setattr("final.parse_pdf.enrich_question", fail_enrich)

    enriched = apply_ai_enrichment(
        output=output,
        ai_base_url="https://example.ngrok-free.dev/v1",
        ai_api_key="token",
        model="local-model",
        max_retries=1,
        ai_max_failures=2,
    )

    assert calls == ["sample.pdf 1번 문제", "sample.pdf 2번 문제"]
    assert enriched["metadata"]["ai_enrichment"]["failed_questions"] == 2
    assert enriched["metadata"]["ai_enrichment"]["skipped_questions"] == 3


def test_ai_enrichment_preserves_existing_review_requirement(monkeypatch):
    from final.parse_pdf import apply_ai_enrichment

    output = {
        "source_pdf": "sample.pdf",
        "questions": [
            {
                "content": "문제",
                "question_source": "sample.pdf 1번 문제",
                "images": [],
                "hint_explanation": "",
                "options": [
                    {
                        "order": 1,
                        "is_correct": True,
                        "content": "선지",
                        "images": [],
                        "option_explanation": "",
                    }
                ],
            }
        ],
        "metadata": {
            "total_questions": 1,
            "total_images": 0,
            "requires_answer_review": True,
            "text_refinement": {
                "enabled": True,
                "low_confidence_questions": [
                    {
                        "question_source": "sample.pdf 1번 문제",
                        "reason": "LLM 텍스트 정제 신뢰도가 낮음",
                    }
                ],
            },
        },
    }

    monkeypatch.setattr("final.parse_pdf.create_openai_client", lambda **kwargs: object())
    monkeypatch.setattr("final.parse_pdf.enrich_question", lambda **kwargs: kwargs["question"])

    enriched = apply_ai_enrichment(
        output=output,
        ai_base_url="https://example.ngrok-free.dev/v1",
        ai_api_key="token",
        model="local-model",
        max_retries=1,
    )

    assert enriched["metadata"]["requires_answer_review"] is True


def test_image_captioning_updates_question_and_option_images(monkeypatch, tmp_path, capsys):
    from final.parse_pdf import apply_image_captioning

    images_dir = tmp_path / "images"
    images_dir.mkdir()
    write_minimal_png(images_dir / "image001.png")
    write_minimal_png(images_dir / "image002.png")

    output = {
        "source_pdf": "sample.pdf",
        "questions": [
            {
                "content": "그림을 보고 고르시오. [image001]",
                "question_source": "sample.pdf 1번 문제",
                "images": [
                    {
                        "image_id": "image001",
                        "image_name": "image001.png",
                        "image_caption": "",
                    }
                ],
                "hint_explanation": "",
                "options": [
                    {
                        "order": 1,
                        "is_correct": False,
                        "content": "선지 그림 [image002]",
                        "images": [
                            {
                                "image_id": "image002",
                                "image_name": "image002.png",
                                "image_caption": "",
                            }
                        ],
                        "option_explanation": "",
                    }
                ],
            }
        ],
        "metadata": {
            "total_questions": 1,
            "total_images": 2,
            "requires_answer_review": False,
        },
    }
    calls = []

    monkeypatch.setattr("final.parse_pdf.create_openai_client", lambda **kwargs: object())

    def fake_caption_image(**kwargs):
        calls.append(
            {
                "image_id": kwargs["image"]["image_id"],
                "option": kwargs.get("option", {}).get("order") if kwargs.get("option") else None,
                "image_path": kwargs["image_path"],
            }
        )
        kwargs["image"]["image_caption"] = f"{kwargs['image']['image_id']} 설명"
        return kwargs["image"]["image_caption"]

    monkeypatch.setattr("final.parse_pdf.caption_image", fake_caption_image)

    captioned = apply_image_captioning(
        output=output,
        output_dir=tmp_path,
        ai_base_url="https://example.ngrok-free.dev/v1",
        ai_api_key="token",
        model="local-model",
        max_retries=1,
    )

    assert calls == [
        {"image_id": "image001", "option": None, "image_path": images_dir / "image001.png"},
        {"image_id": "image002", "option": 1, "image_path": images_dir / "image002.png"},
    ]
    assert captioned["questions"][0]["images"][0]["image_caption"] == "image001 설명"
    assert (
        captioned["questions"][0]["options"][0]["images"][0]["image_caption"]
        == "image002 설명"
    )
    assert captioned["metadata"]["image_captioning"]["captioned_images"] == 2
    assert captioned["metadata"]["image_captioning"]["failed_images"] == 0
    stderr = capsys.readouterr().err
    assert (
        "[image-caption completed] 1/2 sample.pdf 1번 문제 "
        "image001 image001.png"
    ) in stderr
    assert (
        "[image-caption completed] 2/2 sample.pdf 1번 문제 "
        "image002 image002.png"
    ) in stderr


def test_image_captioning_failure_keeps_existing_caption_and_marks_review(
    monkeypatch, tmp_path, capsys
):
    from final.parse_pdf import apply_image_captioning

    images_dir = tmp_path / "images"
    images_dir.mkdir()
    write_minimal_png(images_dir / "image001.png")

    output = {
        "source_pdf": "sample.pdf",
        "questions": [
            {
                "content": "문제 [image001]",
                "question_source": "sample.pdf 1번 문제",
                "images": [
                    {
                        "image_id": "image001",
                        "image_name": "image001.png",
                        "image_caption": "기존 설명",
                    }
                ],
                "hint_explanation": "",
                "options": [],
            }
        ],
        "metadata": {
            "total_questions": 1,
            "total_images": 1,
            "requires_answer_review": False,
        },
    }

    monkeypatch.setattr("final.parse_pdf.create_openai_client", lambda **kwargs: object())

    def fail_caption_image(*args, **kwargs):
        raise RuntimeError("caption failed")

    monkeypatch.setattr("final.parse_pdf.caption_image", fail_caption_image)

    captioned = apply_image_captioning(
        output=output,
        output_dir=tmp_path,
        ai_base_url="https://example.ngrok-free.dev/v1",
        ai_api_key="token",
        model="local-model",
        max_retries=1,
    )

    assert captioned["questions"][0]["images"][0]["image_caption"] == "기존 설명"
    assert captioned["metadata"]["requires_answer_review"] is True
    assert captioned["metadata"]["image_captioning"]["failed_images"] == 1
    assert captioned["metadata"]["image_captioning"]["errors"][0]["image_id"] == "image001"
    assert (
        "[image-caption failed] 1/1 sample.pdf 1번 문제 "
        "image001 image001.png: caption failed"
    ) in capsys.readouterr().err


def test_image_captioning_stops_after_max_failures(monkeypatch, tmp_path):
    from final.parse_pdf import apply_image_captioning

    images_dir = tmp_path / "images"
    images_dir.mkdir()
    for index in range(1, 4):
        write_minimal_png(images_dir / f"image{index:03d}.png")

    output = {
        "source_pdf": "sample.pdf",
        "questions": [
            {
                "content": f"문제 {index} [image{index:03d}]",
                "question_source": f"sample.pdf {index}번 문제",
                "images": [
                    {
                        "image_id": f"image{index:03d}",
                        "image_name": f"image{index:03d}.png",
                        "image_caption": "",
                    }
                ],
                "hint_explanation": "",
                "options": [],
            }
            for index in range(1, 4)
        ],
        "metadata": {
            "total_questions": 3,
            "total_images": 3,
            "requires_answer_review": False,
        },
    }
    calls = []

    monkeypatch.setattr("final.parse_pdf.create_openai_client", lambda **kwargs: object())

    def fail_caption_image(*args, **kwargs):
        calls.append(kwargs["image"]["image_id"])
        raise RuntimeError("invalid json")

    monkeypatch.setattr("final.parse_pdf.caption_image", fail_caption_image)

    captioned = apply_image_captioning(
        output=output,
        output_dir=tmp_path,
        ai_base_url="https://example.ngrok-free.dev/v1",
        ai_api_key="token",
        model="local-model",
        max_retries=1,
        ai_max_failures=1,
    )

    assert calls == ["image001"]
    assert captioned["metadata"]["image_captioning"]["failed_images"] == 1
    assert captioned["metadata"]["image_captioning"]["skipped_images"] == 2


def test_image_captioning_disabled_without_ai_base_url(tmp_path):
    from final.parse_pdf import apply_image_captioning

    output = {
        "source_pdf": "sample.pdf",
        "questions": [],
        "metadata": {"total_questions": 0, "total_images": 0, "requires_answer_review": False},
    }

    captioned = apply_image_captioning(
        output=output,
        output_dir=tmp_path,
        ai_base_url=None,
        ai_api_key="token",
        model="local-model",
        max_retries=1,
    )

    assert captioned["metadata"]["image_captioning"] == {"enabled": False}


def test_text_refiner_updates_question_and_option_content():
    from final.text_refiner import refine_question_text

    class FakeCompletions:
        def create(self, **kwargs):
            content = json.dumps(
                {
                    "content": "객체지향 분석 방법론 중 E-R 다이어그램을 사용하는 것은? [image001]",
                    "options": [
                        {"order": 1, "content": "Coad와 Yourdon 방법"},
                        {"order": 2, "content": "Booch 방법"},
                    ],
                    "corrections": [
                        {
                            "before": "사용 하는 것은 ?",
                            "after": "사용하는 것은?",
                            "reason": "띄어쓰기와 문장부호 위치 정리",
                        }
                    ],
                    "confidence": "high",
                },
                ensure_ascii=False,
            )
            message = type("Message", (), {"content": content})()
            choice = type("Choice", (), {"message": message})()
            return type("Response", (), {"choices": [choice]})()

    class FakeClient:
        def __init__(self):
            self.chat = type("Chat", (), {"completions": FakeCompletions()})()

    question = {
        "content": "객체지향 분석 방법론 중 E-R 다이어그램을 사용 하는 것은 ? [image001]",
        "options": [
            {"order": 1, "content": "Coad 와 Yourdon 방법"},
            {"order": 2, "content": "Booch 방법"},
        ],
    }

    result = refine_question_text(
        client=FakeClient(),
        model="local-model",
        question=question,
        max_retries=1,
    )
    refined = result["question"]

    assert refined["content"] == "객체지향 분석 방법론 중 E-R 다이어그램을 사용하는 것은? [image001]"
    assert refined["options"][0]["content"] == "Coad와 Yourdon 방법"
    assert result["confidence"] == "high"
    assert result["corrections"][0]["before"] == "사용 하는 것은 ?"
    assert result["changes"][0]["field"] == "content"
    assert result["changes"][1]["field"] == "option"


def test_text_refiner_uses_generic_prompt_and_records_corrections():
    from final.text_refiner import refine_question_text

    class FakeCompletions:
        def __init__(self):
            self.calls = 0
            self.prompts = []

        def create(self, **kwargs):
            self.calls += 1
            self.prompts.append(kwargs["messages"][0]["content"])
            content = json.dumps(
                {
                    "content": "럼바우 분석 기법에서 정보 모델링이라고도 하며, 시스템에서 요구되는 객체를 찾는다.",
                    "options": [
                        {
                            "order": 1,
                            "content": "‘ 금융 시스템은 조회, 인출, 입금, 송금의 기능이 있어야 한다 ’",
                        }
                    ],
                    "corrections": [
                        {
                            "before": "조회인출입금송금의 , , ,",
                            "after": "조회, 인출, 입금, 송금의",
                            "reason": "붙은 명사열과 밀린 목록 구분자를 자연스러운 목록 표현으로 복원",
                        }
                    ],
                    "confidence": "high",
                },
                ensure_ascii=False,
            )
            message = type("Message", (), {"content": content})()
            choice = type("Choice", (), {"message": message})()
            return type("Response", (), {"choices": [choice]})()

    class FakeClient:
        def __init__(self):
            self.completions = FakeCompletions()
            self.chat = type("Chat", (), {"completions": self.completions})()

    question = {
        "content": "럼바우 분석 기법에서 정보 모델링이라고도 하며시스 , 템에서 요구되는 객체를 찾는다.",
        "options": [
            {
                "order": 1,
                "content": "‘ 금융 시스템은 조회인출입금송금의 , , , 기능이 있어야 한다 ’",
            }
        ],
    }
    client = FakeClient()

    result = refine_question_text(
        client=client,
        model="local-model",
        question=question,
        max_retries=2,
    )
    refined = result["question"]

    assert "하며, 시스템에서" in refined["content"]
    assert "조회, 인출, 입금, 송금의 기능" in refined["options"][0]["content"]
    assert result["confidence"] == "high"
    assert result["corrections"][0]["after"] == "조회, 인출, 입금, 송금의"
    assert "PDF 파싱 과정에서 글자 순서는 대체로 보존" in client.completions.prompts[0]
    assert "반드시 고쳐야 하는 예시" not in client.completions.prompts[0]
    assert "마크다운 코드블록" in client.completions.prompts[0]
    assert "80자 이내" in client.completions.prompts[0]


def test_text_refinement_marks_unresolved_artifacts_without_hardcoded_fix(monkeypatch):
    from final.parse_pdf import apply_text_refinement

    output = {
        "source_pdf": "sample.pdf",
        "questions": [
            {
                "content": "문제",
                "question_source": "sample.pdf 1번 문제",
                "images": [],
                "hint_explanation": "",
                "options": [
                    {
                        "order": 1,
                        "is_correct": False,
                        "content": "조회인출입금송금의 , , , 기능",
                        "images": [],
                        "option_explanation": "",
                    }
                ],
            }
        ],
        "metadata": {
            "total_questions": 1,
            "total_images": 0,
            "requires_answer_review": False,
        },
    }

    monkeypatch.setattr("final.parse_pdf.create_openai_client", lambda **kwargs: object())
    monkeypatch.setattr(
        "final.parse_pdf.refine_question_text",
        lambda **kwargs: {
            "question": kwargs["question"],
            "corrections": [],
            "confidence": "medium",
        },
    )

    refined = apply_text_refinement(
        output=output,
        ai_base_url="https://example.ngrok-free.dev/v1",
        ai_api_key="token",
        model="local-model",
        max_retries=1,
    )

    assert refined["metadata"]["requires_answer_review"] is True
    assert refined["metadata"]["text_refinement"]["unresolved_artifact_questions"] == 1


def test_text_refinement_records_metadata_and_low_confidence(monkeypatch, capsys):
    from final.parse_pdf import apply_text_refinement

    output = {
        "source_pdf": "sample.pdf",
        "questions": [
            {
                "content": "원문",
                "question_source": "sample.pdf 1번 문제",
                "images": [],
                "hint_explanation": "",
                "options": [
                    {
                        "order": 1,
                        "is_correct": False,
                        "content": "선지",
                        "images": [],
                        "option_explanation": "",
                    }
                ],
            }
        ],
        "metadata": {
            "total_questions": 1,
            "total_images": 0,
            "requires_answer_review": False,
        },
    }

    monkeypatch.setattr("final.parse_pdf.create_openai_client", lambda **kwargs: object())

    def low_confidence_refine(**kwargs):
        kwargs["question"]["content"] = "정제된 원문"
        return {
            "question": kwargs["question"],
            "corrections": [{"before": "원문", "after": "정제된 원문", "reason": "복원"}],
            "confidence": "low",
            "changes": [{"field": "content", "before": "원문", "after": "정제된 원문"}],
        }

    monkeypatch.setattr("final.parse_pdf.refine_question_text", low_confidence_refine)

    refined = apply_text_refinement(
        output=output,
        ai_base_url="https://example.ngrok-free.dev/v1",
        ai_api_key="token",
        model="local-model",
        max_retries=1,
    )

    metadata = refined["metadata"]["text_refinement"]
    captured = capsys.readouterr()
    assert refined["questions"][0]["content"] == "정제된 원문"
    assert refined["metadata"]["requires_answer_review"] is True
    assert metadata["refined_questions"][0]["confidence"] == "low"
    assert metadata["refined_questions"][0]["changes"][0]["after"] == "정제된 원문"
    assert metadata["low_confidence_questions"][0]["question_source"] == "sample.pdf 1번 문제"
    assert "[text-refine changed] sample.pdf 1번 문제 / content" in captured.err
    assert "- before: 원문" in captured.err
    assert "- after: 정제된 원문" in captured.err
    assert refined["metadata"]["text_refinement"]["unresolved_artifact_questions"] == 1


def test_text_refinement_failure_keeps_parser_text(monkeypatch, capsys):
    from final.parse_pdf import apply_text_refinement

    output = {
        "source_pdf": "sample.pdf",
        "questions": [
            {
                "content": "파서 원문",
                "question_source": "sample.pdf 1번 문제",
                "images": [],
                "hint_explanation": "",
                "options": [],
            }
        ],
        "metadata": {
            "total_questions": 1,
            "total_images": 0,
            "requires_answer_review": False,
        },
    }

    monkeypatch.setattr("final.parse_pdf.create_openai_client", lambda **kwargs: object())

    def fail_refine(*args, **kwargs):
        raise RuntimeError("text refine failed")

    monkeypatch.setattr("final.parse_pdf.refine_question_text", fail_refine)

    refined = apply_text_refinement(
        output=output,
        ai_base_url="https://example.ngrok-free.dev/v1",
        ai_api_key="token",
        model="local-model",
        max_retries=1,
    )

    assert refined["questions"][0]["content"] == "파서 원문"
    assert refined["metadata"]["requires_answer_review"] is True
    assert refined["metadata"]["text_refinement"]["failed_questions"] == 1
    assert "[text-refine failed] sample.pdf 1번 문제: text refine failed" in capsys.readouterr().err


def test_text_refinement_skips_after_timeout_failures(monkeypatch, capsys):
    from final.parse_pdf import apply_text_refinement

    output = {
        "source_pdf": "sample.pdf",
        "questions": [
            {
                "content": f"문제 {index}",
                "question_source": f"sample.pdf {index}번 문제",
                "images": [],
                "hint_explanation": "",
                "options": [],
            }
            for index in range(1, 4)
        ],
        "metadata": {
            "total_questions": 3,
            "total_images": 0,
            "requires_answer_review": False,
        },
    }

    monkeypatch.setattr("final.parse_pdf.create_openai_client", lambda **kwargs: object())

    calls = []

    def fail_then_succeed(*args, **kwargs):
        calls.append(kwargs["question"]["question_source"])
        if len(calls) == 1:
            raise RuntimeError("Request timed out.")
        return {
            "question": kwargs["question"],
            "corrections": [],
            "confidence": "medium",
            "changes": [],
        }

    monkeypatch.setattr("final.parse_pdf.refine_question_text", fail_then_succeed)

    refined = apply_text_refinement(
        output=output,
        ai_base_url="https://example.ngrok-free.dev/v1",
        ai_api_key="token",
        model="local-model",
        max_retries=1,
        ai_max_failures=1,
    )

    stderr = capsys.readouterr().err
    assert calls == ["sample.pdf 1번 문제"]
    assert refined["metadata"]["text_refinement"]["failed_questions"] == 0
    assert refined["metadata"]["text_refinement"]["timeout_questions"] == 1
    assert refined["metadata"]["text_refinement"]["skipped_questions"] == 2
    assert "[text-refine failed] sample.pdf 1번 문제: Request timed out." in stderr
    assert "[text-refine skipped] 2 questions skipped after 1 failures." in stderr


def test_text_refinement_logs_skipped_questions_after_non_timeout_failures(monkeypatch, capsys):
    from final.parse_pdf import apply_text_refinement

    output = {
        "source_pdf": "sample.pdf",
        "questions": [
            {
                "content": f"문제 {index}",
                "question_source": f"sample.pdf {index}번 문제",
                "images": [],
                "hint_explanation": "",
                "options": [],
            }
            for index in range(1, 4)
        ],
        "metadata": {
            "total_questions": 3,
            "total_images": 0,
            "requires_answer_review": False,
        },
    }

    monkeypatch.setattr("final.parse_pdf.create_openai_client", lambda **kwargs: object())

    def fail_refine(*args, **kwargs):
        raise RuntimeError("invalid json")

    monkeypatch.setattr("final.parse_pdf.refine_question_text", fail_refine)

    refined = apply_text_refinement(
        output=output,
        ai_base_url="https://example.ngrok-free.dev/v1",
        ai_api_key="token",
        model="local-model",
        max_retries=1,
        ai_max_failures=1,
    )

    stderr = capsys.readouterr().err
    assert refined["metadata"]["text_refinement"]["failed_questions"] == 1
    assert refined["metadata"]["text_refinement"]["timeout_questions"] == 0
    assert refined["metadata"]["text_refinement"]["skipped_questions"] == 2
    assert "[text-refine failed] sample.pdf 1번 문제: invalid json" in stderr
    assert "[text-refine skipped] 2 questions skipped after 1 failures." in stderr
