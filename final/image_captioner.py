#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""최종 JSON 이미지 caption 생성 유틸리티."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

from final.ai_enricher import encode_image_as_data_url, request_json_with_retries


def iter_image_caption_targets(output: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """최종 JSON에서 caption 대상 이미지를 문제/선지 맥락과 함께 순회한다."""
    for question in output.get("questions", []):
        for image in question.get("images", []):
            if isinstance(image, dict):
                yield {"question": question, "option": None, "image": image}
        for option in question.get("options", []):
            for image in option.get("images", []):
                if isinstance(image, dict):
                    yield {"question": question, "option": option, "image": image}


def build_image_caption_prompt(
    *,
    question: dict[str, Any],
    image: dict[str, Any],
    option: dict[str, Any] | None = None,
) -> str:
    """이미지와 함께 보낼 문제 맥락 prompt를 만든다."""
    context: dict[str, Any] = {
        "question_source": question.get("question_source", ""),
        "question_content": question.get("content", ""),
        "options": [
            {
                "order": item.get("order"),
                "content": item.get("content", ""),
            }
            for item in question.get("options", [])
            if isinstance(item, dict)
        ],
        "target_image": {
            "image_id": image.get("image_id", ""),
            "image_name": image.get("image_name", ""),
            "location": "option" if option else "question",
        },
    }
    if option:
        context["target_option"] = {
            "order": option.get("order"),
            "content": option.get("content", ""),
        }

    return (
        "첨부된 시험 문제 이미지를 설명하라. JSON만 출력하라.\n"
        "이미지에서 실제로 보이는 내용만 설명하고, "
        "문제 정답이나 해설을 새로 만들지 마라.\n"
        "문제 텍스트와 선지 텍스트는 이미지가 어떤 맥락에 놓였는지 "
        "이해하기 위한 참고 정보다.\n"
        "이미지 안의 글자, 도형, 표, 관계, 배치가 보이면 "
        "풀이자가 이미지를 식별할 수 있게 간결히 설명하라.\n"
        "image_caption은 한국어로 작성하라.\n"
        "보이지 않는 내용은 추측하지 마라.\n"
        '출력 형식: {"image_caption": "이미지 설명"}\n\n'
        "문제 맥락:\n"
        f"{json.dumps(context, ensure_ascii=False, indent=2)}"
    )


def build_image_caption_message_content(
    *,
    question: dict[str, Any],
    image: dict[str, Any],
    image_path: Path,
    option: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    return [
        {
            "type": "text",
            "text": build_image_caption_prompt(question=question, image=image, option=option),
        },
        {
            "type": "image_url",
            "image_url": {
                "url": encode_image_as_data_url(image_path),
            },
        },
    ]


def _normalize_caption(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()


def caption_image(
    *,
    client,
    model: str,
    question: dict[str, Any],
    image: dict[str, Any],
    image_path: Path,
    max_retries: int = 3,
    option: dict[str, Any] | None = None,
) -> str:
    """단일 이미지 caption을 생성해 image dict에 반영한다."""
    payload = request_json_with_retries(
        client=client,
        model=model,
        messages=[
            {
                "role": "user",
                "content": build_image_caption_message_content(
                    question=question,
                    image=image,
                    image_path=image_path,
                    option=option,
                ),
            }
        ],
        max_retries=max_retries,
    )
    caption = _normalize_caption(payload.get("image_caption"))
    if not caption:
        raise ValueError("AI 응답에 image_caption이 없다.")
    image["image_caption"] = caption
    return caption
