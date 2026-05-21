import importlib
import json
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
    assert importlib.import_module("final.result_pdf_parser.extract_pdf")
    assert importlib.import_module("final.result_pdf_parser.generate_answer")
    assert importlib.import_module("final.result_pdf_parser.batch_generate_answer")
    assert importlib.import_module("final.result_pdf_parser.generate_concept")
    assert importlib.import_module("final.result_pdf_parser.batch_generate_concept")
    assert importlib.import_module("final.result_pdf_parser.extract_questions")
    assert importlib.import_module("final.text_refiner")


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


def test_parse_pdf_auto_falls_back_to_result_parser(monkeypatch, tmp_path):
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
    monkeypatch.setattr(parse_pdf, "run_result_parser", result_success)

    output_path = parse_pdf.run_pipeline(
        pdf_path=pdf_path,
        output_dir=tmp_path / "out",
        parser_name="auto",
        dpi=72,
        ai_base_url=None,
        model="local-model",
        max_retries=1,
    )

    saved = json.loads(output_path.read_text(encoding="utf-8"))
    assert saved["questions"][0]["content"] == "문제"


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


def test_text_refinement_does_not_skip_after_timeout(monkeypatch, capsys):
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
    assert calls == ["sample.pdf 1번 문제", "sample.pdf 2번 문제", "sample.pdf 3번 문제"]
    assert refined["metadata"]["text_refinement"]["failed_questions"] == 0
    assert refined["metadata"]["text_refinement"]["timeout_questions"] == 1
    assert refined["metadata"]["text_refinement"]["skipped_questions"] == 0
    assert "[text-refine failed] sample.pdf 1번 문제: Request timed out." in stderr
    assert "[text-refine skipped]" not in stderr


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
