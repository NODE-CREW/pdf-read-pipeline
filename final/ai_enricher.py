#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OpenAI-compatible endpoint를 이용한 최종 JSON 보강 유틸리티."""

from __future__ import annotations

import base64
import json
import mimetypes
from pathlib import Path
from typing import Any


def create_openai_client(
    *,
    base_url: str,
    api_key: str = "any-string-ok",
    timeout: float = 10.0,
):
    from openai import OpenAI

    return OpenAI(base_url=base_url, api_key=api_key, timeout=timeout)


def encode_image_as_data_url(image_path: Path) -> str:
    mime_type = mimetypes.guess_type(image_path.name)[0] or "image/png"
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def parse_json_response(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        stripped = stripped.removeprefix("json").strip()
    payload = json.loads(stripped)
    if not isinstance(payload, dict):
        raise ValueError("AI 응답은 JSON object여야 한다.")
    return payload


def request_json_with_retries(
    *,
    client,
    model: str,
    messages: list[dict[str, Any]],
    max_retries: int = 3,
) -> dict[str, Any]:
    last_error: Exception | None = None
    for _ in range(max(max_retries, 1)):
        response = client.chat.completions.create(model=model, messages=messages)
        content = response.choices[0].message.content or ""
        try:
            return parse_json_response(content)
        except (json.JSONDecodeError, ValueError) as exc:
            last_error = exc
    raise RuntimeError(f"유효한 JSON AI 응답을 받지 못했다: {last_error}")


def build_enrichment_prompt(question: dict[str, Any]) -> str:
    return (
        "다음 시험 문제 JSON을 보강하라. JSON만 출력하라. "
        "필드는 image_captions, hint_explanation, option_explanations, correct_orders만 허용한다. "
        "image_captions는 image_id를 key로 하는 객체다. "
        "option_explanations는 선지 order를 문자열 key로 하는 객체다. "
        "correct_orders는 정답 선지 번호 배열이다.\n"
        f"{json.dumps(question, ensure_ascii=False, indent=2)}"
    )


def enrich_question(
    *,
    client,
    model: str,
    question: dict[str, Any],
    max_retries: int = 3,
) -> dict[str, Any]:
    """단일 최종 문제 dict에 AI 보강 결과를 병합한다."""
    payload = request_json_with_retries(
        client=client,
        model=model,
        messages=[{"role": "user", "content": build_enrichment_prompt(question)}],
        max_retries=max_retries,
    )

    image_captions = payload.get("image_captions", {})
    if isinstance(image_captions, dict):
        for image in question.get("images", []):
            caption = image_captions.get(image.get("image_id"))
            if isinstance(caption, str) and caption.strip():
                image["image_caption"] = caption.strip()
        for option in question.get("options", []):
            for image in option.get("images", []):
                caption = image_captions.get(image.get("image_id"))
                if isinstance(caption, str) and caption.strip():
                    image["image_caption"] = caption.strip()

    hint_explanation = payload.get("hint_explanation")
    if isinstance(hint_explanation, str) and hint_explanation.strip():
        question["hint_explanation"] = hint_explanation.strip()

    option_explanations = payload.get("option_explanations", {})
    if isinstance(option_explanations, dict):
        for option in question.get("options", []):
            explanation = option_explanations.get(str(option.get("order")))
            if isinstance(explanation, str) and explanation.strip():
                option["option_explanation"] = explanation.strip()

    correct_orders = payload.get("correct_orders", [])
    if isinstance(correct_orders, list) and correct_orders:
        correct_order_set = {int(order) for order in correct_orders if str(order).isdigit()}
        for option in question.get("options", []):
            option["is_correct"] = int(option.get("order", 0)) in correct_order_set

    return question
