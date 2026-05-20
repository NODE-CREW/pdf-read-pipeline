#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""최종 문제 JSON 구조 생성 및 간단 검증."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any


def _image_source_path(image: dict[str, Any]) -> Path | None:
    for key in ("crop_path", "source", "path"):
        value = image.get(key)
        if value:
            return Path(str(value))
    return None


def _copy_image(source_path: Path | None, destination_path: Path) -> None:
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    if source_path is not None and source_path.is_file():
        shutil.copy2(source_path, destination_path)
        return
    destination_path.touch()


def _build_image_entry(
    *,
    raw_image: dict[str, Any],
    image_id: str,
    image_name: str,
) -> dict[str, str]:
    caption = str(raw_image.get("image_caption", raw_image.get("caption", ""))).strip()
    return {
        "image_id": image_id,
        "image_name": image_name,
        "image_caption": caption,
    }


def _append_image_tokens(content: str, images: list[dict[str, str]]) -> str:
    tokens = [f"[{image['image_id']}]" for image in images]
    if not tokens:
        return content
    suffix = "\n".join(tokens)
    return f"{content}\n{suffix}".strip() if content else suffix


def build_final_output(normalized: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    """공통 정규화 결과를 최종 JSON dict로 변환하고 이미지를 복사한다."""
    output_dir = Path(output_dir)
    image_dir = output_dir / "images"
    image_counter = 1
    requires_answer_review = False
    final_questions: list[dict[str, Any]] = []

    for question in normalized.get("questions", []):
        question_images: list[dict[str, str]] = []
        for raw_image in question.get("images", []):
            if not isinstance(raw_image, dict):
                continue
            image_id = f"image{image_counter:03d}"
            image_name = f"{image_id}.png"
            _copy_image(_image_source_path(raw_image), image_dir / image_name)
            question_images.append(
                _build_image_entry(raw_image=raw_image, image_id=image_id, image_name=image_name)
            )
            image_counter += 1

        final_options: list[dict[str, Any]] = []
        has_correct = False
        for option in question.get("options", []):
            option_images: list[dict[str, str]] = []
            for raw_image in option.get("images", []):
                if not isinstance(raw_image, dict):
                    continue
                image_id = f"image{image_counter:03d}"
                image_name = f"{image_id}.png"
                _copy_image(_image_source_path(raw_image), image_dir / image_name)
                option_images.append(
                    _build_image_entry(raw_image=raw_image, image_id=image_id, image_name=image_name)
                )
                image_counter += 1

            is_correct = bool(option.get("is_correct", False))
            has_correct = has_correct or is_correct
            final_options.append(
                {
                    "order": int(option.get("order", 0)),
                    "is_correct": is_correct,
                    "content": _append_image_tokens(str(option.get("content", "")).strip(), option_images),
                    "images": option_images,
                    "option_explanation": str(option.get("option_explanation", "")).strip(),
                }
            )

        if final_options and not has_correct:
            requires_answer_review = True

        final_questions.append(
            {
                "content": _append_image_tokens(str(question.get("content", "")).strip(), question_images),
                "question_source": str(question.get("question_source", "")).strip(),
                "images": question_images,
                "hint_explanation": str(question.get("hint_explanation", "")).strip(),
                "options": final_options,
            }
        )

    output = {
        "source_pdf": normalized.get("source_pdf", ""),
        "questions": final_questions,
        "metadata": {
            "total_questions": len(final_questions),
            "total_images": image_counter - 1,
            "requires_answer_review": requires_answer_review,
        },
    }
    validate_final_output(output)
    return output


def validate_final_output(output: dict[str, Any]) -> None:
    required_question_keys = {
        "content",
        "question_source",
        "images",
        "hint_explanation",
        "options",
    }
    for question in output.get("questions", []):
        missing = required_question_keys - set(question)
        if missing:
            raise ValueError(f"문제 필드가 누락되었다: {sorted(missing)}")
        for option in question["options"]:
            if set(option) != {
                "order",
                "is_correct",
                "content",
                "images",
                "option_explanation",
            }:
                raise ValueError("선지 필드가 최종 스키마와 다르다.")
