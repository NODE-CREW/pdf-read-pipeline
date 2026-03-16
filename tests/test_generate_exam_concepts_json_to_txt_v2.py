import importlib.util
import json
import sys
from pathlib import Path

import pytest


def load_module():
    module_name = "generate_exam_concepts_json_to_txt_v2"
    module_path = Path(__file__).resolve().parents[1] / "9-2_generate_exam_concepts_json_to_txt.py"
    spec = importlib.util.spec_from_file_location(module_name, str(module_path))
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def write_minimal_png(path: Path) -> None:
    path.write_bytes(
        bytes.fromhex(
            "89504E470D0A1A0A"
            "0000000D4948445200000001000000010802000000907753DE"
            "0000000C4944415408D763F8FFFF3F0005FE02FEA7A69D6E"
            "0000000049454E44AE426082"
        )
    )


def build_valid_response(*, question_ids: list[int]) -> str:
    return json.dumps(
        {
            "concepts": [
                {
                    "concept_id": 200,
                    "concept_name": "공통 개념",
                    "summary": "두세 문장으로 요약한 공통 개념 설명이다. 학생이 무엇을 배워야 하는지 드러낸다.",
                    "explanation": (
                        "첫째 문단이다.\n\n"
                        "둘째 문단이다.\n\n"
                        "셋째 문단이다.\n\n"
                        "넷째 문단이다."
                    ),
                }
            ],
            "question_concept_mapping": [
                {
                    "mapping_id": index,
                    "question_id": question_id,
                    "concept_id": 200,
                }
                for index, question_id in enumerate(question_ids, start=1)
            ],
        },
        ensure_ascii=False,
    )


def test_validate_response_payload_rejects_multiple_concepts():
    module = load_module()
    payload = {
        "concepts": [
            {
                "concept_id": 200,
                "concept_name": "공통 개념",
                "summary": "요약이다. 요약이다.",
                "explanation": "문단1\n\n문단2\n\n문단3\n\n문단4",
            },
            {
                "concept_id": 201,
                "concept_name": "분리 개념",
                "summary": "요약이다. 요약이다.",
                "explanation": "문단1\n\n문단2\n\n문단3\n\n문단4",
            },
        ],
        "question_concept_mapping": [
            {
                "mapping_id": 1,
                "question_id": 7,
                "concept_id": 200,
            },
            {
                "mapping_id": 2,
                "question_id": 8,
                "concept_id": 201,
            },
        ],
    }

    with pytest.raises(ValueError, match="concepts는 정확히 1개"):
        module.validate_response_payload(payload, expected_question_ids=[7, 8])


def test_validate_response_payload_requires_exactly_one_mapping_per_question():
    module = load_module()
    payload = {
        "concepts": [
            {
                "concept_id": 200,
                "concept_name": "공통 개념",
                "summary": "요약이다. 요약이다.",
                "explanation": "문단1\n\n문단2\n\n문단3\n\n문단4",
            }
        ],
        "question_concept_mapping": [
            {
                "mapping_id": 1,
                "question_id": 7,
                "concept_id": 200,
            },
            {
                "mapping_id": 2,
                "question_id": 7,
                "concept_id": 200,
            },
        ],
    }

    with pytest.raises(ValueError, match="모든 question_id가 정확히 한 번씩"):
        module.validate_response_payload(payload, expected_question_ids=[7, 8])


def test_validate_question_ids_defaults_to_image_order():
    module = load_module()

    assert module.validate_question_ids(image_count=2, question_ids=None) == [1, 2]


def test_validate_question_ids_requires_same_count():
    module = load_module()

    with pytest.raises(ValueError, match="question-id"):
        module.validate_question_ids(image_count=3, question_ids=[10, 11])


def test_build_user_message_content_embeds_prompt_and_images(tmp_path):
    module = load_module()
    image1 = tmp_path / "q1.png"
    image2 = tmp_path / "q2.png"
    write_minimal_png(image1)
    write_minimal_png(image2)

    content = module.build_user_message_content(
        question_ids=[7, 8],
        image_paths=[image1, image2],
    )

    assert content[0]["type"] == "input_text"
    assert "{{INPUT_JSON}}" not in content[0]["text"]
    assert '"question_id": 7' in content[0]["text"]
    assert [item["type"] for item in content[1:]] == ["input_image", "input_image"]
    assert content[1]["image_url"].startswith("data:image/png;base64,")
    assert content[1]["detail"] == "high"


def test_parse_and_validate_response_text_rejects_missing_question_mapping():
    module = load_module()
    response_text = json.dumps(
        {
            "concepts": [
                {
                    "concept_id": 200,
                    "concept_name": "공통 개념",
                    "summary": "요약이다. 요약이다.",
                    "explanation": "문단1\n\n문단2\n\n문단3\n\n문단4",
                }
            ],
            "question_concept_mapping": [
                {
                    "mapping_id": 1,
                    "question_id": 7,
                    "concept_id": 200,
                }
            ],
        },
        ensure_ascii=False,
    )

    with pytest.raises(ValueError, match="모든 question_id가 정확히 한 번씩"):
        module.parse_and_validate_response_text(response_text, expected_question_ids=[7, 8])


def test_save_output_text_pretty_prints_json(tmp_path):
    module = load_module()
    output_path = tmp_path / "result.txt"

    module.save_output_text(
        output_path=output_path,
        response_text=build_valid_response(question_ids=[7, 8]),
        expected_question_ids=[7, 8],
    )

    saved = output_path.read_text(encoding="utf-8")
    data = json.loads(saved)

    assert data["concepts"][0]["concept_id"] == 200
    assert "\n  " in saved


def test_request_retries_when_response_contains_multiple_concepts(tmp_path):
    module = load_module()
    image1 = tmp_path / "q1.png"
    image2 = tmp_path / "q2.png"
    write_minimal_png(image1)
    write_minimal_png(image2)

    responses = iter(
        [
            json.dumps(
                {
                    "concepts": [
                        {
                            "concept_id": 200,
                            "concept_name": "개념1",
                            "summary": "요약이다. 요약이다.",
                            "explanation": "문단1\n\n문단2\n\n문단3\n\n문단4",
                        },
                        {
                            "concept_id": 201,
                            "concept_name": "개념2",
                            "summary": "요약이다. 요약이다.",
                            "explanation": "문단1\n\n문단2\n\n문단3\n\n문단4",
                        },
                    ],
                    "question_concept_mapping": [
                        {"mapping_id": 1, "question_id": 7, "concept_id": 200},
                        {"mapping_id": 2, "question_id": 8, "concept_id": 201},
                    ],
                },
                ensure_ascii=False,
            ),
            build_valid_response(question_ids=[7, 8]),
        ]
    )
    seen_attempts = []

    class FakeResponses:
        def create(self, **kwargs):
            seen_attempts.append(kwargs)
            return type("FakeResponse", (), {"output_text": next(responses)})()

    class FakeClient:
        def __init__(self):
            self.responses = FakeResponses()

    result = module.request_concepts_json(
        client=FakeClient(),
        model="gpt-5-mini",
        question_ids=[7, 8],
        image_paths=[image1, image2],
        max_retries=2,
    )

    assert "공통 개념" in result
    assert len(seen_attempts) == 2


def test_main_requests_openai_and_writes_txt(monkeypatch, tmp_path):
    module = load_module()
    image1 = tmp_path / "q1.png"
    image2 = tmp_path / "q2.png"
    output_path = tmp_path / "concepts.txt"
    write_minimal_png(image1)
    write_minimal_png(image2)

    captured = {}

    class FakeResponses:
        def create(self, **kwargs):
            captured.update(kwargs)
            return type("FakeResponse", (), {"output_text": build_valid_response(question_ids=[101, 102])})()

    class FakeClient:
        def __init__(self):
            self.responses = FakeResponses()

    monkeypatch.setattr(module, "create_openai_client", lambda: FakeClient())

    module.main(
        [
            "--image",
            str(image1),
            "--image",
            str(image2),
            "--question-id",
            "101",
            "--question-id",
            "102",
            "--output",
            str(output_path),
        ]
    )

    assert captured["model"] == "gpt-5-mini"
    assert captured["input"][0]["role"] == "user"
    assert captured["text"]["format"]["type"] == "json_schema"
    assert output_path.exists() is True
    assert json.loads(output_path.read_text(encoding="utf-8"))["question_concept_mapping"][1]["question_id"] == 102


def test_create_openai_client_uses_shared_module_loader(monkeypatch):
    module = load_module()
    sentinel_client = object()
    shared_module = type(
        "SharedModule",
        (),
        {
            "create_openai_client": lambda self: sentinel_client,
        },
    )()
    monkeypatch.setattr(module, "load_shared_module", lambda: shared_module)

    assert module.create_openai_client() is sentinel_client
