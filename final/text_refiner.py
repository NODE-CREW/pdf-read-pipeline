#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LLM으로 파싱 텍스트의 OCR/띄어쓰기 오류를 정제한다."""

from __future__ import annotations

import json
import re
from typing import Any

from final.ai_enricher import request_json_with_retries


PARTICLE_AFTER_SPLIT_RE = re.compile(
    r"[가-힣A-Za-z]{1,6}\s*,\s*[가-힣A-Za-z]{1,6}"
    r"(?=(?:에서|으로|은|는|이|가|을|를|의|와|과|도|만|에|로))"
)
EMPTY_COMMA_RE = re.compile(r",\s*,")
LONG_GLUE_RE = re.compile(r"[가-힣]{8,}(?:의|을|를|은|는|이|가)(?=\s)")
CONNECTIVE_GLUE_RE = re.compile(
    r"(?:하며|이고|이며|되며|하여|하고)[가-힣]{2,}"
    r"(?=(?:에서|으로|은|는|이|가|을|를|의|와|과|도|만|에|로))"
)


def repair_mechanical_parse_artifacts(text: str) -> str:
    """문맥 판단 없이 안전한 기계적 공백/문장부호 오류만 정리한다."""
    repaired = text

    repaired = re.sub(r"\s+([,?.!])", r"\1", repaired)
    repaired = re.sub(r"([,?.!])([^\s\]\),.?!])", r"\1 \2", repaired)
    repaired = re.sub(r"\s{2,}", " ", repaired)
    return repaired.strip()


def detect_text_artifacts(text: str) -> list[str]:
    """특정 문장 치환이 아니라 남아 있는 파싱 아티팩트 유형을 탐지한다."""
    findings: list[str] = []
    if PARTICLE_AFTER_SPLIT_RE.search(text):
        findings.append("단어 내부가 쉼표로 분리된 패턴")
    if EMPTY_COMMA_RE.search(text):
        findings.append("빈 쉼표 나열 패턴")
    if CONNECTIVE_GLUE_RE.search(text):
        findings.append("연결 어미 뒤 단어가 붙은 패턴")
    if LONG_GLUE_RE.search(text):
        findings.append("여러 한국어 단어가 길게 붙은 패턴")
    return findings


def collect_question_text_artifacts(question: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    for finding in detect_text_artifacts(str(question.get("content", ""))):
        findings.append(f"content: {finding}")
    for option in question.get("options", []):
        order = option.get("order")
        for finding in detect_text_artifacts(str(option.get("content", ""))):
            findings.append(f"option {order}: {finding}")
    return findings


def build_text_refine_prompt(question: dict[str, Any], artifacts: list[str] | None = None) -> str:
    payload = {
        "content": repair_mechanical_parse_artifacts(str(question.get("content", ""))),
        "options": [
            {
                "order": option.get("order"),
                "content": repair_mechanical_parse_artifacts(str(option.get("content", ""))),
            }
            for option in question.get("options", [])
        ],
    }
    artifact_hint = ""
    if artifacts:
        artifact_hint = (
            "아래 탐지된 문제 유형은 반드시 다시 확인해서 고쳐라.\n"
            + "\n".join(f"- {artifact}" for artifact in artifacts)
            + "\n"
        )
    return (
        "다음 텍스트는 PDF에서 추출된 시험 문제 문장이다.\n"
        "PDF 파싱 과정에서 글자 순서는 대체로 보존되지만, 단어 경계, 띄어쓰기, "
        "구두점 위치, 목록 구분자가 깨질 수 있다.\n\n"
        "너의 작업은 추출 텍스트를 원문 시험지에 가까운 자연스러운 한국어 문장으로 복원하는 것이다.\n\n"
        "복원 원칙:\n"
        "- 글자의 의미 순서는 최대한 유지한다.\n"
        "- 새 개념이나 원문에 없을 법한 정보를 추가하지 않는다.\n"
        "- 붙어 있는 한국어 어절이나 명사열은 문맥상 자연스러운 최소 단위로 분리한다.\n"
        "- 잘못 삽입되거나 밀린 구두점은 문장 구조에 맞게 재배치한다.\n"
        "- 병렬 항목, 기능 나열, 단계 나열, 문서/산출물 나열처럼 보이는 부분은 자연스러운 목록 표현으로 복원한다.\n"
        "- 조사, 어미, 괄호, 따옴표, 영문 약어 주변의 띄어쓰기를 한국어 시험 문장 관례에 맞게 정리한다.\n"
        "- 확실하지 않은 부분은 과도하게 바꾸지 말고 원문을 최대한 유지한다.\n"
        "- [image001] 같은 이미지 토큰은 절대 수정하거나 제거하지 않는다.\n\n"
        "수정 범위:\n"
        "- 문제 본문 content\n"
        "- 선지 options[].content\n\n"
        "수정하지 말 것:\n"
        "- 정답 여부\n"
        "- 해설\n"
        "- 이미지 설명\n"
        "- 문제 출처\n"
        "- 선지 순서\n"
        "- 이미지 토큰\n\n"
        f"{artifact_hint}"
        "출력은 JSON 객체 하나만 사용하라. 마크다운 코드블록, ```json, 설명 문장을 절대 출력하지 마라.\n"
        "JSON은 한 줄이어도 좋다. 문자열은 반드시 닫아라.\n"
        "corrections는 꼭 필요한 핵심 수정만 최대 5개까지 작성하라.\n"
        "corrections.before와 corrections.after는 각각 80자 이내의 짧은 핵심 구간만 넣어라.\n"
        "corrections.reason은 60자 이내로 짧게 작성하라.\n"
        "출력 형식:\n"
        "{\n"
        '  "content": "정제된 문제 본문",\n'
        '  "options": [{"order": 1, "content": "정제된 선지"}],\n'
        '  "corrections": [{"before": "80자 이내", "after": "80자 이내", "reason": "60자 이내"}],\n'
        '  "confidence": "high|medium|low"\n'
        "}\n\n"
        "입력:\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def _valid_refined_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    refined = repair_mechanical_parse_artifacts(value)
    return refined or None


def _normalize_corrections(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    corrections: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        before = str(item.get("before", "")).strip()
        after = str(item.get("after", "")).strip()
        reason = str(item.get("reason", "")).strip()
        if before or after or reason:
            corrections.append({"before": before, "after": after, "reason": reason})
    return corrections


def _normalize_confidence(value: Any) -> str:
    confidence = str(value or "").strip().lower()
    if confidence in {"high", "medium", "low"}:
        return confidence
    return "medium"


def _snapshot_question_texts(question: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": str(question.get("content", "")),
        "options": {
            int(option.get("order", 0)): str(option.get("content", ""))
            for option in question.get("options", [])
        },
    }


def _collect_text_changes(
    before: dict[str, Any],
    question: dict[str, Any],
) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    after_content = str(question.get("content", ""))
    if before["content"] != after_content:
        changes.append(
            {
                "field": "content",
                "before": before["content"],
                "after": after_content,
            }
        )

    before_options = before["options"]
    for option in question.get("options", []):
        order = int(option.get("order", 0))
        before_content = before_options.get(order, "")
        after_option_content = str(option.get("content", ""))
        if before_content != after_option_content:
            changes.append(
                {
                    "field": "option",
                    "order": order,
                    "before": before_content,
                    "after": after_option_content,
                }
            )
    return changes


def refine_question_text(
    *,
    client,
    model: str,
    question: dict[str, Any],
    max_retries: int = 3,
) -> dict[str, Any]:
    """단일 문제 텍스트를 정제하고 정제 metadata를 반환한다."""
    question["content"] = repair_mechanical_parse_artifacts(str(question.get("content", "")))
    for option in question.get("options", []):
        option["content"] = repair_mechanical_parse_artifacts(str(option.get("content", "")))
    original_texts = _snapshot_question_texts(question)

    all_corrections: list[dict[str, str]] = []
    confidence = "medium"
    for _ in range(max(max_retries, 1)):
        artifacts = collect_question_text_artifacts(question)
        payload = request_json_with_retries(
            client=client,
            model=model,
            messages=[{"role": "user", "content": build_text_refine_prompt(question, artifacts)}],
            max_retries=1,
        )
        all_corrections.extend(_normalize_corrections(payload.get("corrections")))
        confidence = _normalize_confidence(payload.get("confidence"))

        refined_content = _valid_refined_text(payload.get("content"))
        if refined_content is not None:
            question["content"] = refined_content

        refined_options = payload.get("options", [])
        if isinstance(refined_options, list):
            by_order = {
                int(option["order"]): option
                for option in refined_options
                if isinstance(option, dict) and str(option.get("order", "")).isdigit()
            }
            for option in question.get("options", []):
                order = int(option.get("order", 0))
                refined_option = by_order.get(order)
                if not refined_option:
                    continue
                refined_option_content = _valid_refined_text(refined_option.get("content"))
                if refined_option_content is not None:
                    option["content"] = refined_option_content

        if not collect_question_text_artifacts(question):
            break

    return {
        "question": question,
        "corrections": all_corrections,
        "confidence": confidence,
        "changes": _collect_text_changes(original_texts, question),
    }
