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
