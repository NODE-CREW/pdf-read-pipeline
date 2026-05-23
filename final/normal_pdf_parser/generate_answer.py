#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import base64
import json
import mimetypes
import os
from pathlib import Path


PROMPT_TEMPLATE = """
너는 시험 문제 이미지 기반 정답/해설 JSON 생성기다.

문제 이미지와 선택지 이미지들을 분석하여 정답 1개를 고르고, 각 선택지 explanation과 정답 explanation을 한국어로 작성한다.

반드시 아래 규칙을 따른다:
- JSON만 출력한다.
- JSON 바깥 텍스트, 코드블록, 마크다운을 출력하지 않는다.
- 모든 key와 string value는 ASCII 쌍따옴표 " 만 사용한다.
- 스마트 따옴표(“ ” ‘ ’)와 전각 따옴표(＂)를 사용하지 않는다.
- 스페이스 2칸 들여쓰기 pretty JSON으로 출력한다.
- trailing comma를 사용하지 않는다.
- 스키마 외 필드를 추가하지 않는다.
- null을 사용하지 않는다.
- explanation은 한국어 "~이다", "~다" 체로 작성한다.
- 정답은 반드시 하나만 선택한다.
- 문제를 완전히 읽기 어렵더라도 가능한 범위에서 합리적으로 추론한다.
- explanations에서 이미지 파일명이나 URL을 언급하지 않는다.

출력 스키마:
{
  "questions": [
    {
      "test_id": 0,
      "question_id": 0,
      "question_image_url": ""
    }
  ],
  "options": [
    {
      "option_id": 1,
      "question_id": 0,
      "option_number": 1,
      "option_image_url": "",
      "explanation": ""
    }
  ],
  "answers": [
    {
      "answer_id": 1,
      "question_id": 0,
      "correct_option_number": 1,
      "explanation": ""
    }
  ]
}

작성 규칙:
- questions는 1개 객체만 넣는다.
- options는 보이는 선택지 개수만큼 넣는다.
- answers는 1개 객체만 넣는다.
- test_id와 question_id는 입력값을 그대로 사용한다.
- question_image_url에는 question_image_urls의 첫 번째 값을 넣는다.
- option_id와 option_number는 1부터 순서대로 부여한다.
- option_image_url에는 option_image_urls를 순서대로 넣는다.
- 정답 선택지 explanation은 왜 맞는지 설명한다.
- 오답 선택지 explanation은 왜 틀렸는지 설명한다.
- answers.explanation은 정답 근거와 오답 비교를 포함해 3~6문장으로 작성한다.

입력:
{{INPUT_JSON}}

최종 pretty JSON만 출력하라.
""".strip()

SMART_QUOTES = ("“", "”", "‘", "’", "＂")

OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["questions", "options", "answers"],
    "properties": {
        "questions": {
            "type": "array",
            "minItems": 1,
            "maxItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["test_id", "question_id", "question_image_url"],
                "properties": {
                    "test_id": {"type": "integer"},
                    "question_id": {"type": "integer"},
                    "question_image_url": {"type": "string"},
                },
            },
        },
        "options": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "option_id",
                    "question_id",
                    "option_number",
                    "option_image_url",
                    "explanation",
                ],
                "properties": {
                    "option_id": {"type": "integer"},
                    "question_id": {"type": "integer"},
                    "option_number": {"type": "integer"},
                    "option_image_url": {"type": "string"},
                    "explanation": {"type": "string"},
                },
            },
        },
        "answers": {
            "type": "array",
            "minItems": 1,
            "maxItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "answer_id",
                    "question_id",
                    "correct_option_number",
                    "explanation",
                ],
                "properties": {
                    "answer_id": {"type": "integer"},
                    "question_id": {"type": "integer"},
                    "correct_option_number": {"type": "integer"},
                    "explanation": {"type": "string"},
                },
            },
        },
    },
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--image",
        dest="images",
        action="append",
        required=True,
        help="분석에 사용할 이미지 경로. 총 2장 또는 3장",
    )
    parser.add_argument("--test-id", type=int, default=1, help="출력 questions.test_id 기본값은 1")
    parser.add_argument("--question-id", type=int, default=1, help="출력 question_id 기본값은 1")
    parser.add_argument("--output", required=True, help="결과 txt 파일 경로")
    parser.add_argument("--model", default="gpt-5-mini", help='기본값은 "gpt-5-mini"')
    parser.add_argument("--max-retries", type=int, default=3, help="응답 검증 실패 시 최대 재시도 횟수")
    return parser.parse_args(argv)


def find_dotenv_path() -> Path | None:
    for candidate in (Path.cwd() / ".env", Path(__file__).resolve().parent / ".env"):
        if candidate.is_file():
            return candidate
    return None


def parse_dotenv_value(raw_value: str) -> str:
    value = raw_value.strip()
    if not value:
        return ""
    if value[:1] == value[-1:] and value[:1] in ('"', "'"):
        return value[1:-1]
    return value.split(" #", 1)[0].strip()


def load_openai_api_key() -> str:
    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if api_key:
        return api_key

    dotenv_path = find_dotenv_path()
    if dotenv_path is None:
        raise RuntimeError("OPENAI_API_KEY가 없고 .env 파일도 찾을 수 없다.")

    for line in dotenv_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        if key.strip() == "OPENAI_API_KEY":
            api_key = parse_dotenv_value(value)
            if api_key:
                return api_key
            break

    raise RuntimeError("OPENAI_API_KEY가 환경변수와 .env 파일 모두에 설정되어 있지 않다.")


def create_openai_client():
    from openai import OpenAI

    return OpenAI(api_key=load_openai_api_key())


def validate_image_paths(image_paths: list[str]) -> list[Path]:
    if len(image_paths) not in (2, 3):
        raise ValueError("이미지는 2장 또는 3장만 전달할 수 있다.")

    resolved_paths = [Path(path).expanduser().resolve() for path in image_paths]
    missing_paths = [str(path) for path in resolved_paths if not path.is_file()]
    if missing_paths:
        raise ValueError(f"이미지 파일을 찾을 수 없다: {', '.join(missing_paths)}")
    return resolved_paths


def build_input_json(*, test_id: int, question_id: int, image_paths: list[Path]) -> str:
    payload = {
        "test_id": test_id,
        "question_id": question_id,
        "question_image_urls": [str(image_paths[0])],
        "option_image_urls": [str(path) for path in image_paths[1:]],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def build_prompt(input_json_text: str) -> str:
    return PROMPT_TEMPLATE.replace("{{INPUT_JSON}}", input_json_text)


def encode_image_as_data_url(image_path: Path) -> str:
    mime_type = mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def build_user_message_content(input_json_text: str, image_paths: list[Path]) -> list[dict]:
    content = [{"type": "input_text", "text": build_prompt(input_json_text)}]
    for image_path in image_paths:
        content.append(
            {
                "type": "input_image",
                "image_url": encode_image_as_data_url(image_path),
                "detail": "high",
            }
        )
    return content


def build_text_format() -> dict:
    return {
        "format": {
            "type": "json_schema",
            "name": "exam_answer_json",
            "strict": True,
            "schema": OUTPUT_SCHEMA,
        }
    }


def has_disallowed_quotes(text: str) -> bool:
    return any(char in text for char in SMART_QUOTES)


def parse_and_validate_response_text(response_text: str) -> dict:
    if has_disallowed_quotes(response_text):
        raise ValueError("응답에 스마트 따옴표 또는 전각 따옴표가 포함되어 있다.")
    return json.loads(response_text)


def request_exam_json(
    *,
    client,
    model: str,
    input_json_text: str,
    image_paths: list[Path],
    max_retries: int,
) -> str:
    last_error = None
    request_input = [{"role": "user", "content": build_user_message_content(input_json_text, image_paths)}]

    for _ in range(max_retries):
        response = client.responses.create(
            model=model,
            input=request_input,
            text=build_text_format(),
        )
        response_text = getattr(response, "output_text", "")
        try:
            parse_and_validate_response_text(response_text)
            return response_text
        except (json.JSONDecodeError, ValueError) as exc:
            last_error = exc

    raise RuntimeError(f"유효한 JSON 응답을 받지 못했다: {last_error}")


def save_output_text(*, output_path: Path, response_text: str) -> None:
    parsed = parse_and_validate_response_text(response_text)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(parsed, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    image_paths = validate_image_paths(args.images)
    input_json_text = build_input_json(
        test_id=args.test_id,
        question_id=args.question_id,
        image_paths=image_paths,
    )
    response_text = request_exam_json(
        client=create_openai_client(),
        model=args.model,
        input_json_text=input_json_text,
        image_paths=image_paths,
        max_retries=max(args.max_retries, 1),
    )
    save_output_text(output_path=Path(args.output), response_text=response_text)


if __name__ == "__main__":
    main()
