#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""기존 파서 출력을 최종 스키마 직전의 공통 구조로 정규화한다."""

from __future__ import annotations

from pathlib import Path
from typing import Any

_CIRCLED_ORDER = {
    "①": 1,
    "②": 2,
    "③": 3,
    "④": 4,
    "⑤": 5,
    "⑥": 6,
    "⑦": 7,
    "⑧": 8,
    "⑨": 9,
    "⑩": 10,
}


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_choice(raw_choice: dict[str, Any]) -> dict[str, Any]:
    order = raw_choice.get(
        "order",
        raw_choice.get("number", raw_choice.get("option_number", raw_choice.get("label", 0))),
    )
    if isinstance(order, str) and order in _CIRCLED_ORDER:
        order = _CIRCLED_ORDER[order]
    try:
        order = int(order)
    except (TypeError, ValueError):
        order = 0

    return {
        "order": order,
        "content": _as_text(raw_choice.get("content", raw_choice.get("text", ""))),
        "is_correct": bool(raw_choice.get("is_correct", False)),
        "images": list(raw_choice.get("images", [])),
        "option_explanation": _as_text(raw_choice.get("option_explanation", "")),
    }


def _extract_correct_orders(raw_question: dict[str, Any]) -> set[int]:
    answer = raw_question.get("answer", raw_question.get("correct_answer"))
    if answer is None:
        return set()
    if isinstance(answer, int):
        return {answer}
    text = str(answer).strip()
    if text in _CIRCLED_ORDER:
        return {_CIRCLED_ORDER[text]}
    orders: set[int] = set()
    for part in text.replace(" ", "").split(","):
        if part.isdigit():
            orders.add(int(part))
    return orders


def _normalize_question(raw_question: dict[str, Any], source_pdf: Path) -> dict[str, Any]:
    question_number = raw_question.get(
        "question_number",
        raw_question.get("question_no", raw_question.get("question_id", 0)),
    )
    try:
        question_number = int(question_number)
    except (TypeError, ValueError):
        question_number = 0

    content = _as_text(
        raw_question.get(
            "content",
            raw_question.get("question_text", raw_question.get("stem", "")),
        )
    )
    description = _as_text(raw_question.get("description", ""))
    if description:
        content = "\n".join(part for part in (content, description) if part)

    raw_options = raw_question.get("options", raw_question.get("choices", []))
    options = [
        _normalize_choice(choice)
        for choice in raw_options
        if isinstance(choice, dict)
    ]
    options.sort(key=lambda option: option["order"])
    correct_orders = _extract_correct_orders(raw_question)
    if correct_orders:
        for option in options:
            option["is_correct"] = option["order"] in correct_orders

    question_source = _as_text(raw_question.get("question_source", ""))
    if not question_source:
        question_source = f"{source_pdf.name} {question_number}번 문제"

    return {
        "question_number": question_number,
        "content": content,
        "question_source": question_source,
        "images": list(raw_question.get("images", raw_question.get("assets", []))),
        "hint_explanation": _as_text(
            raw_question.get("hint_explanation", raw_question.get("explanation", ""))
        ),
        "options": options,
    }


def normalize_parser_result(parser_result: dict[str, Any], source_pdf: Path) -> dict[str, Any]:
    """sinagong/normal 계열 파서 출력을 공통 dict로 맞춘다."""
    questions = [
        _normalize_question(question, source_pdf)
        for question in parser_result.get("questions", [])
        if isinstance(question, dict)
    ]
    questions.sort(key=lambda question: question["question_number"])

    return {
        "source_pdf": source_pdf.name,
        "questions": questions,
    }
