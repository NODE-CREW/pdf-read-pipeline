#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import importlib.util
import json
from functools import lru_cache
from pathlib import Path


PROMPT_TEMPLATE = """
너는 시험 문제 이미지들을 분석하여, 여러 문제가 공통으로 설명하거나 평가하는 핵심 학습 개념을 추출하고, 이를 학생용 학습 개념 JSON으로 정리하는 도우미다.

입력으로는 문제 이미지가 1장 이상 주어진다.
각 문제의 문제문과 선택지를 읽고, 여러 문제를 관통하는 공통 개념을 추론하라.

[목표]
- 각 문제의 정답 자체보다, 여러 문제가 공통으로 다루는 핵심 개념을 찾는다.
- 공통 개념은 단편적인 세부 사실이 아니라 학생이 학습해야 할 상위 개념이어야 한다.
- 여러 문제가 하나의 동일한 상위 개념으로 묶이면 concept는 1개만 생성한다.
- 공통 개념이 명확히 둘 이상으로 분리될 때만 concept를 여러 개 생성한다.
- explanation은 학생 교육용 설명이므로, 이 JSON만 읽어도 개념을 이해할 수 있을 정도로 충분히 자세하고 이해하기 쉽게 작성한다.

[공통 개념 추출 기준]
- 문제들의 공통분모가 되는 학습 개념을 찾는다.
- 문제 문장을 단순 반복하지 말고, 왜 이 문제들이 같은 개념에 속하는지 설명 가능한 수준으로 일반화한다.
- 개념명은 교과서식 또는 학습용 명칭으로 작성한다.
- 지나치게 좁은 개념명이나 문제별 개별 포인트 나열은 피한다.
- 지나치게 넓어서 학습 가치가 떨어지는 추상적 개념명도 피한다.
- 이미지에 보이는 정보에 근거하여 합리적으로 일반화하되, 과도한 추측은 하지 않는다.

[작성 규칙]
- summary는 2~4문장으로 작성한다.
- explanation은 공통 개념 중심으로 작성하고, 문제별 정답 해설처럼 쓰지 않는다.
- explanation에는 아래 요소가 자연스럽게 포함되도록 한다.
  1. 개념의 정의
  2. 개념이 중요한 이유
  3. 문제들과의 연결
  4. 헷갈리기 쉬운 포인트 또는 오개념
  5. 필요한 경우 관련 하위 개념, 종류, 해결 방법, 비교 포인트
- explanation은 최소 4문단 이상으로 작성하고, 각 문단은 서로 다른 역할을 갖도록 한다.
- 문제 번호는 question_concept_mapping에만 사용하고, explanation 본문은 개념 자체 설명에 집중한다.
- 개념 설명은 한국어로 작성한다.

[출력 스키마]
{
  "concepts": [
    {
      "concept_id": 200,
      "concept_name": "개념명",
      "summary": "요약",
      "explanation": "상세 설명"
    }
  ],
  "question_concept_mapping": [
    {
      "mapping_id": 1,
      "question_id": 7,
      "concept_id": 200
    }
  ]
}

[출력 절대 규칙]
- 출력은 반드시 유효한 JSON 객체 하나만 출력한다.
- JSON 바깥의 설명, 서문, 주석, 마크다운, 코드블록은 절대 출력하지 않는다.
- 출력은 반드시 pretty-printed JSON이어야 한다.
- 들여쓰기는 스페이스 2칸으로 한다.
- 한 줄짜리 minified JSON은 절대 출력하지 않는다.
- 모든 key와 모든 string value는 반드시 ASCII double quote(")만 사용한다.
- 다음 문자는 절대 출력하지 않는다: “ ” ‘ ’ ＂
- trailing comma를 절대 사용하지 않는다.
- 줄바꿈과 들여쓰기를 포함하더라도 JSON parser로 바로 파싱 가능해야 한다.

[출력 전 자체 검증]
최종 출력 전에 반드시 아래를 점검하라.
1. JSON 외의 텍스트가 없는가?
2. 모든 key가 ASCII double quote(")로 감싸져 있는가?
3. 모든 문자열 값이 ASCII double quote(")로 감싸져 있는가?
4. “ ” ‘ ’ ＂ 문자가 전혀 없는가?
5. 출력이 스페이스 2칸 들여쓰기의 pretty JSON인가?
6. trailing comma가 없는가?
7. explanation이 충분히 자세한 학생용 설명인가?
8. 문제별 정답 해설이 아니라 공통 개념 중심 설명인가?
9. 최종 결과가 유효한 JSON인가?

검증에 하나라도 실패하면 수정한 뒤, 최종 JSON만 출력하라.

아래 입력 JSON의 questions 배열 순서가 뒤이어 제공되는 이미지 순서와 정확히 일치한다.
question_id는 question_concept_mapping에만 사용하고, explanation 본문에는 문제 번호를 직접 나열하지 않는다.

입력:
{{INPUT_JSON}}
""".strip()

OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["concepts", "question_concept_mapping"],
    "properties": {
        "concepts": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["concept_id", "concept_name", "summary", "explanation"],
                "properties": {
                    "concept_id": {"type": "integer"},
                    "concept_name": {"type": "string"},
                    "summary": {"type": "string"},
                    "explanation": {"type": "string"},
                },
            },
        },
        "question_concept_mapping": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["mapping_id", "question_id", "concept_id"],
                "properties": {
                    "mapping_id": {"type": "integer"},
                    "question_id": {"type": "integer"},
                    "concept_id": {"type": "integer"},
                },
            },
        },
    },
}


@lru_cache(maxsize=1)
def load_shared_module():
    module_path = Path(__file__).resolve().with_name("9_generate_exam_answer_json_to_txt.py")
    spec = importlib.util.spec_from_file_location("generate_exam_answer_json_shared", str(module_path))
    if spec is None or spec.loader is None:
        raise RuntimeError("공통 OpenAI 유틸 모듈을 불러올 수 없다.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def create_openai_client():
    shared_module = load_shared_module()
    return shared_module.create_openai_client()


def validate_image_paths(image_paths: list[str]) -> list[Path]:
    return load_shared_module().validate_image_paths(image_paths)


def encode_image_as_data_url(image_path: Path) -> str:
    return load_shared_module().encode_image_as_data_url(image_path)


def has_disallowed_quotes(text: str) -> bool:
    return load_shared_module().has_disallowed_quotes(text)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--image",
        dest="images",
        action="append",
        required=True,
        help="분석에 사용할 문제 이미지 경로. 총 2장 또는 3장",
    )
    parser.add_argument(
        "--question-id",
        dest="question_ids",
        action="append",
        type=int,
        help="각 이미지에 대응하는 question_id. 생략하면 이미지 순서대로 1부터 부여",
    )
    parser.add_argument("--output", required=True, help="결과 txt 파일 경로")
    parser.add_argument("--model", default="gpt-5-mini", help='기본값은 "gpt-5-mini"')
    parser.add_argument("--max-retries", type=int, default=3, help="응답 검증 실패 시 최대 재시도 횟수")
    return parser.parse_args(argv)


def validate_question_ids(*, image_count: int, question_ids: list[int] | None) -> list[int]:
    if question_ids is None:
        return list(range(1, image_count + 1))
    if len(question_ids) != image_count:
        raise ValueError("--question-id 개수는 이미지 개수와 같아야 한다.")
    return question_ids


def build_input_json(question_ids: list[int]) -> str:
    payload = {
        "questions": [
            {
                "question_id": question_id,
                "image_index": index,
            }
            for index, question_id in enumerate(question_ids, start=1)
        ]
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def build_prompt(question_ids: list[int]) -> str:
    return PROMPT_TEMPLATE.replace("{{INPUT_JSON}}", build_input_json(question_ids))


def build_user_message_content(question_ids: list[int], image_paths: list[Path]) -> list[dict]:
    content = [{"type": "input_text", "text": build_prompt(question_ids)}]
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
            "name": "exam_concepts_json",
            "strict": True,
            "schema": OUTPUT_SCHEMA,
        }
    }


def validate_response_payload(payload: dict, expected_question_ids: list[int]) -> None:
    if set(payload.keys()) != {"concepts", "question_concept_mapping"}:
        raise ValueError("루트 필드는 concepts와 question_concept_mapping만 허용된다.")

    concepts = payload["concepts"]
    mappings = payload["question_concept_mapping"]
    if not isinstance(concepts, list) or not concepts:
        raise ValueError("concepts는 1개 이상이어야 한다.")
    if not isinstance(mappings, list) or not mappings:
        raise ValueError("question_concept_mapping은 1개 이상이어야 한다.")

    concept_ids = set()
    for concept in concepts:
        if set(concept.keys()) != {"concept_id", "concept_name", "summary", "explanation"}:
            raise ValueError("concepts 항목의 필드가 올바르지 않다.")
        if not isinstance(concept["concept_id"], int):
            raise ValueError("concept_id는 정수여야 한다.")
        for key in ("concept_name", "summary", "explanation"):
            if not isinstance(concept[key], str) or not concept[key].strip():
                raise ValueError(f"{key}는 비어 있지 않은 문자열이어야 한다.")
        concept_ids.add(concept["concept_id"])

    mapped_question_ids = []
    for mapping in mappings:
        if set(mapping.keys()) != {"mapping_id", "question_id", "concept_id"}:
            raise ValueError("question_concept_mapping 항목의 필드가 올바르지 않다.")
        if not isinstance(mapping["mapping_id"], int):
            raise ValueError("mapping_id는 정수여야 한다.")
        if not isinstance(mapping["question_id"], int):
            raise ValueError("question_id는 정수여야 한다.")
        if mapping["concept_id"] not in concept_ids:
            raise ValueError("mapping의 concept_id가 concepts에 존재하지 않는다.")
        mapped_question_ids.append(mapping["question_id"])

    expected_ids = set(expected_question_ids)
    actual_ids = set(mapped_question_ids)
    if actual_ids != expected_ids:
        raise ValueError("모든 question_id가 정확히 한 번 이상 매핑되어야 한다.")


def parse_and_validate_response_text(response_text: str, expected_question_ids: list[int]) -> dict:
    if has_disallowed_quotes(response_text):
        raise ValueError("응답에 스마트 따옴표 또는 전각 따옴표가 포함되어 있다.")
    parsed = json.loads(response_text)
    validate_response_payload(parsed, expected_question_ids)
    return parsed


def request_concepts_json(
    *,
    client,
    model: str,
    question_ids: list[int],
    image_paths: list[Path],
    max_retries: int,
) -> str:
    last_error = None
    request_input = [{"role": "user", "content": build_user_message_content(question_ids, image_paths)}]

    for _ in range(max_retries):
        response = client.responses.create(
            model=model,
            input=request_input,
            text=build_text_format(),
        )
        response_text = getattr(response, "output_text", "")
        try:
            parse_and_validate_response_text(response_text, question_ids)
            return response_text
        except (json.JSONDecodeError, ValueError) as exc:
            last_error = exc

    raise RuntimeError(f"유효한 JSON 응답을 받지 못했다: {last_error}")


def save_output_text(*, output_path: Path, response_text: str, expected_question_ids: list[int]) -> None:
    parsed = parse_and_validate_response_text(response_text, expected_question_ids)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(parsed, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    image_paths = validate_image_paths(args.images)
    question_ids = validate_question_ids(image_count=len(image_paths), question_ids=args.question_ids)
    response_text = request_concepts_json(
        client=create_openai_client(),
        model=args.model,
        question_ids=question_ids,
        image_paths=image_paths,
        max_retries=max(args.max_retries, 1),
    )
    save_output_text(
        output_path=Path(args.output),
        response_text=response_text,
        expected_question_ids=question_ids,
    )


if __name__ == "__main__":
    main()
