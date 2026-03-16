import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest


def load_module():
    module_name = "generate_exam_answer_json_to_txt"
    module_path = Path(__file__).resolve().parents[1] / "9_generate_exam_answer_json_to_txt.py"
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


def test_validate_image_paths_requires_two_or_three_images(tmp_path):
    module = load_module()
    image1 = tmp_path / "1.png"
    image2 = tmp_path / "2.png"
    image3 = tmp_path / "3.png"
    write_minimal_png(image1)
    write_minimal_png(image2)
    write_minimal_png(image3)

    assert module.validate_image_paths([str(image1), str(image2)]) == [
        image1.resolve(),
        image2.resolve(),
    ]
    assert module.validate_image_paths([str(image1), str(image2), str(image3)]) == [
        image1.resolve(),
        image2.resolve(),
        image3.resolve(),
    ]

    with pytest.raises(ValueError, match="2장 또는 3장"):
        module.validate_image_paths([str(image1)])


def test_build_user_message_content_embeds_prompt_and_images(tmp_path):
    module = load_module()
    image1 = tmp_path / "question.png"
    image2 = tmp_path / "choices.png"
    write_minimal_png(image1)
    write_minimal_png(image2)

    content = module.build_user_message_content(
        input_json_text=module.build_input_json(
            test_id=1,
            question_id=2,
            image_paths=[image1.resolve(), image2.resolve()],
        ),
        image_paths=[image1, image2],
    )

    assert content[0]["type"] == "input_text"
    assert "{{INPUT_JSON}}" not in content[0]["text"]
    assert '"test_id": 1' in content[0]["text"]
    assert [item["type"] for item in content[1:]] == ["input_image", "input_image"]
    assert content[1]["image_url"].startswith("data:image/png;base64,")
    assert content[1]["detail"] == "high"


def test_build_input_json_uses_image_paths_and_ids(tmp_path):
    module = load_module()
    image1 = tmp_path / "question.png"
    image2 = tmp_path / "choices_1.png"
    image3 = tmp_path / "choices_2.png"
    write_minimal_png(image1)
    write_minimal_png(image2)
    write_minimal_png(image3)

    payload = json.loads(
        module.build_input_json(
            test_id=7,
            question_id=9,
            image_paths=[image1.resolve(), image2.resolve(), image3.resolve()],
        )
    )

    assert payload == {
        "test_id": 7,
        "question_id": 9,
        "question_image_urls": [str(image1.resolve())],
        "option_image_urls": [str(image2.resolve()), str(image3.resolve())],
    }


def test_save_output_text_pretty_prints_json(tmp_path):
    module = load_module()
    output_path = tmp_path / "result.txt"

    module.save_output_text(
        output_path=output_path,
        response_text='{"questions":[{"test_id":1,"question_id":2,"question_image_url":"q"}],"options":[],"answers":[{"answer_id":1,"question_id":2,"correct_option_number":1,"explanation":"정답이다"}]}',
    )

    saved = output_path.read_text(encoding="utf-8")
    data = json.loads(saved)

    assert data["questions"][0]["test_id"] == 1
    assert "\n  " in saved


def test_main_requests_openai_and_writes_txt(monkeypatch, tmp_path):
    module = load_module()
    image1 = tmp_path / "question.png"
    image2 = tmp_path / "choices.png"
    output_path = tmp_path / "answer.txt"
    write_minimal_png(image1)
    write_minimal_png(image2)

    captured = {}

    class FakeResponses:
        def __init__(self):
            self.calls = 0

        def create(self, **kwargs):
            self.calls += 1
            captured.update(kwargs)
            return type(
                "FakeResponse",
                (),
                {
                    "output_text": json.dumps(
                        {
                            "questions": [
                                {
                                    "test_id": 7,
                                    "question_id": 9,
                                    "question_image_url": str(image1.resolve()),
                                }
                            ],
                            "options": [
                                {
                                    "option_id": 1,
                                    "question_id": 9,
                                    "option_number": 1,
                                    "option_image_url": str(image2.resolve()),
                                    "explanation": "오답이다",
                                }
                            ],
                            "answers": [
                                {
                                    "answer_id": 1,
                                    "question_id": 9,
                                    "correct_option_number": 1,
                                    "explanation": "정답 근거다. 오답과 비교도 포함한다. 결론이다.",
                                }
                            ],
                        },
                        ensure_ascii=False,
                    )
                },
            )()

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
            "--test-id",
            "7",
            "--question-id",
            "9",
            "--output",
            str(output_path),
        ]
    )

    assert captured["model"] == "gpt-5-mini"
    assert captured["input"][0]["role"] == "user"
    assert captured["text"]["format"]["type"] == "json_schema"
    assert output_path.exists() is True
    assert json.loads(output_path.read_text(encoding="utf-8"))["answers"][0]["correct_option_number"] == 1


def test_request_retries_when_response_contains_smart_quotes(monkeypatch, tmp_path):
    module = load_module()
    image1 = tmp_path / "question.png"
    image2 = tmp_path / "choices.png"
    write_minimal_png(image1)
    write_minimal_png(image2)

    responses = iter(
        [
            '{"questions":[{"test_id":1,"question_id":1,"question_image_url":"q"}],"options":[],"answers":[{"answer_id":1,"question_id":1,"correct_option_number":1,"explanation":"“잘못된 출력”"}]}',
            '{"questions":[{"test_id":1,"question_id":1,"question_image_url":"q"}],"options":[],"answers":[{"answer_id":1,"question_id":1,"correct_option_number":1,"explanation":"정상 출력이다"}]}',
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

    result = module.request_exam_json(
        client=FakeClient(),
        model="gpt-5-mini",
        input_json_text='{"test_id":1,"question_id":1,"question_image_urls":["q"],"option_image_urls":["o"]}',
        image_paths=[image1, image2],
        max_retries=2,
    )

    assert "정상 출력이다" in result
    assert len(seen_attempts) == 2


def test_create_openai_client_reads_api_key_from_dotenv(tmp_path, monkeypatch):
    module = load_module()
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text('OPENAI_API_KEY="test-key"\n', encoding="utf-8")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(module, "find_dotenv_path", lambda: dotenv_path)

    original_openai = sys.modules.get("openai")

    class FakeOpenAI:
        def __init__(self, api_key):
            self.api_key = api_key

    sys.modules["openai"] = type("FakeOpenAIModule", (), {"OpenAI": FakeOpenAI})()
    try:
        client = module.create_openai_client()
    finally:
        if original_openai is None:
            sys.modules.pop("openai", None)
        else:
            sys.modules["openai"] = original_openai

    assert client.api_key == "test-key"


def test_create_openai_client_uses_environment_before_dotenv(monkeypatch):
    module = load_module()
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    monkeypatch.setattr(module, "find_dotenv_path", lambda: None)

    original_openai = sys.modules.get("openai")

    class FakeOpenAI:
        def __init__(self, api_key):
            self.api_key = api_key

    sys.modules["openai"] = type("FakeOpenAIModule", (), {"OpenAI": FakeOpenAI})()
    try:
        client = module.create_openai_client()
    finally:
        if original_openai is None:
            sys.modules.pop("openai", None)
        else:
            sys.modules["openai"] = original_openai

    assert client.api_key == "env-key"
