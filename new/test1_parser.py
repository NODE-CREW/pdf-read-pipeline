#!/usr/bin/env python3
"""data/test-1.pdf 전용 문제/선택지 추출기."""

from __future__ import annotations

import argparse
from collections import deque
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import fitz
from PIL import Image, ImageDraw


QUESTION_RE = re.compile(r"^(\d{1,3})\.\s*(.*)$")
CHOICE_RE = re.compile(r"([①②③④])")
SUBJECT_RE = re.compile(r"^제\s*\d*\s*과목")
FOOTER_RE = re.compile(r"^-\s*\d+\s*-$")
NUMBER_LIST_RE = re.compile(r"(?:\d+\s*,\s*){4,}\d+")
CHOICE_LINE_RE = re.compile(r"^[①②③④]")

CHOICE_NUMBER_MAP = {"①": 1, "②": 2, "③": 3, "④": 4}


@dataclass
class TextLine:
    page_number: int
    column_index: int
    text: str
    bbox: tuple[float, float, float, float]


def normalize_text(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def should_skip_line(text: str) -> bool:
    normalized = normalize_text(text)
    if not normalized:
        return True
    if normalized in {"1 회", "정답 및 해설", "저작권 안내"}:
        return True
    if FOOTER_RE.match(normalized):
        return True
    if normalized.startswith("2024 년 1 회 정보처리기사 필기"):
        return True
    if "기출문제 & 정답 및 해설" in normalized:
        return True
    if normalized.startswith("이 자료는 시나공 카페 회원"):
        return True
    if normalized.startswith("다른 매체에 옮겨 실을 수 없으며"):
        return True
    if normalized.startswith("※ 다음 문제를 읽고 알맞은 것을 골라"):
        return True
    if normalized.startswith("답란 ("):
        return True
    if SUBJECT_RE.match(normalized):
        return True
    return False


def page_content_bounds(page_number: int) -> tuple[float, float]:
    if page_number == 1:
        return 215.0, 790.0
    return 60.0, 790.0


def group_words_to_lines(words: list[tuple], page_number: int, column_index: int) -> list[TextLine]:
    if not words:
        return []

    sorted_words = sorted(words, key=lambda item: (item[1], item[0]))
    grouped: list[list[tuple]] = []
    for word in sorted_words:
        x0, y0, x1, y1, *_ = word
        if not grouped:
            grouped.append([word])
            continue
        last_group = grouped[-1]
        last_y = sum(item[1] for item in last_group) / len(last_group)
        if abs(y0 - last_y) <= 3.0:
            last_group.append(word)
        else:
            grouped.append([word])

    lines: list[TextLine] = []
    for group in grouped:
        group.sort(key=lambda item: item[0])
        text = normalize_text(" ".join(str(item[4]) for item in group))
        if should_skip_line(text):
            continue
        x0 = min(item[0] for item in group)
        y0 = min(item[1] for item in group)
        x1 = max(item[2] for item in group)
        y1 = max(item[3] for item in group)
        lines.append(TextLine(page_number, column_index, text, (x0, y0, x1, y1)))
    return lines


def extract_ordered_lines(doc: fitz.Document) -> list[TextLine]:
    all_lines: list[TextLine] = []
    content_page_count = max(doc.page_count - 1, 0)
    for page_index in range(content_page_count):
        page_number = page_index + 1
        page = doc[page_index]
        min_y, max_y = page_content_bounds(page_number)
        mid_x = page.rect.width / 2
        left_words: list[tuple] = []
        right_words: list[tuple] = []

        for word in page.get_text("words"):
            x0, y0, x1, y1, *_ = word
            if y0 < min_y or y1 > max_y:
                continue
            target = left_words if ((x0 + x1) / 2) < mid_x else right_words
            target.append(word)

        all_lines.extend(group_words_to_lines(left_words, page_number, 0))
        all_lines.extend(group_words_to_lines(right_words, page_number, 1))
    return all_lines


def merge_bboxes(boxes: Iterable[tuple[float, float, float, float]]) -> list[float]:
    boxes = list(boxes)
    return [
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    ]


def parse_choice_text(text: str) -> tuple[str, list[dict[str, object]]]:
    normalized = normalize_text(text)
    matches = list(CHOICE_RE.finditer(normalized))
    if not matches:
        return normalized, []

    stem = normalize_text(normalized[: matches[0].start()])
    choices: list[dict[str, object]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(normalized)
        label = match.group(1)
        choice_text = normalize_text(normalized[match.end() : end])
        choices.append({"number": CHOICE_NUMBER_MAP[label], "text": choice_text})
    return stem, choices


def build_questions(lines: list[TextLine]) -> list[dict[str, object]]:
    questions: list[dict[str, object]] = []
    current: dict[str, object] | None = None

    for line in lines:
        question_match = QUESTION_RE.match(line.text)
        if question_match:
            if current is not None:
                questions.append(current)
            current = {
                "question_number": int(question_match.group(1)),
                "page_number": line.page_number,
                "raw_lines": [line],
                "excluded_line_indexes": set(),
                "images": [],
            }
            continue

        if current is None:
            continue

        current["raw_lines"].append(line)

    if current is not None:
        questions.append(current)

    return questions


def get_included_lines(question: dict[str, object]) -> list[TextLine]:
    excluded_line_indexes = question.get("excluded_line_indexes", set())
    return [
        line
        for index, line in enumerate(question["raw_lines"])
        if index not in excluded_line_indexes
    ]


def finalize_question(raw_question: dict[str, object]) -> dict[str, object]:
    included_lines = get_included_lines(raw_question)
    line_texts = [line.text for line in included_lines]
    if line_texts and is_question_start_line(line_texts[0]):
        line_texts[0] = normalize_text(QUESTION_RE.match(line_texts[0]).group(2))
    text = normalize_text(" ".join(line_texts))
    question_text, choices = parse_choice_text(text)
    return {
        "question_number": raw_question["question_number"],
        "page_number": raw_question["page_number"],
        "question_text": question_text,
        "description": "",
        "choices": choices,
        "images": raw_question["images"],
        "bounding_box": [
            round(value, 3) for value in merge_bboxes(line.bbox for line in raw_question["raw_lines"])
        ],
    }


def rect_contains(rect: fitz.Rect, point_x: float, point_y: float) -> bool:
    return rect.x0 <= point_x <= rect.x1 and rect.y0 <= point_y <= rect.y1


def is_question_start_line(text: str) -> bool:
    return QUESTION_RE.match(text) is not None


def is_choice_line(text: str) -> bool:
    return CHOICE_LINE_RE.match(text) is not None


def is_text_representable_visual(question_text: str) -> bool:
    textual_markers = (
        "SELECT ",
        "UPDATE ",
        "#include",
        "public class",
        "System.out",
        "printf",
        "while (",
    )
    return any(marker in question_text for marker in textual_markers) or bool(NUMBER_LIST_RE.search(question_text))


def calculate_text_overlap_ratio(page: fitz.Page, rect: fitz.Rect) -> tuple[float, int]:
    rect_area = rect.get_area()
    if rect_area <= 0:
        return 0.0, 0

    overlap_area = 0.0
    overlap_count = 0
    for word in page.get_text("words"):
        word_rect = fitz.Rect(word[:4])
        intersection = rect & word_rect
        if intersection.is_empty:
            continue
        overlap_area += intersection.get_area()
        overlap_count += 1

    return overlap_area / rect_area, overlap_count


def is_text_heavy_candidate(page: fitz.Page, rect: fitz.Rect) -> bool:
    text_overlap_ratio, overlap_count = calculate_text_overlap_ratio(page, rect)
    return text_overlap_ratio >= 0.35 and overlap_count >= 8


def get_visual_band_from_lines(lines: list[TextLine]) -> tuple[float, float] | None:
    if not lines:
        return None

    stem_bottom = lines[0].bbox[3]
    choice_tops = [line.bbox[1] for line in lines if is_choice_line(line.text)]
    if not choice_tops:
        return None

    first_choice_top = min(choice_tops)
    if first_choice_top <= stem_bottom:
        return None

    return stem_bottom, first_choice_top


def collect_visual_candidates(doc: fitz.Document) -> dict[int, list[fitz.Rect]]:
    candidates: dict[int, list[fitz.Rect]] = {}
    content_page_count = max(doc.page_count - 1, 0)
    for page_index in range(content_page_count):
        page_number = page_index + 1
        page = doc[page_index]
        min_y, max_y = page_content_bounds(page_number)
        page_candidates: list[fitz.Rect] = []
        for rect_like in page.cluster_drawings():
            rect = fitz.Rect(rect_like)
            if rect.y0 < min_y or rect.y1 > max_y:
                continue
            if rect.width < 20 or rect.height < 12:
                continue
            if is_text_heavy_candidate(page, rect):
                continue
            page_candidates.append(rect)
        candidates[page_number] = page_candidates
    return candidates


def clamp_rect(rect: fitz.Rect, page_rect: fitz.Rect) -> fitz.Rect:
    return fitz.Rect(
        max(page_rect.x0, rect.x0),
        max(page_rect.y0, rect.y0),
        min(page_rect.x1, rect.x1),
        min(page_rect.y1, rect.y1),
    )


def save_crop(page: fitz.Page, rect: fitz.Rect, crop_path: Path, dpi: int) -> None:
    crop_path.parent.mkdir(parents=True, exist_ok=True)
    matrix = fitz.Matrix(dpi / 72, dpi / 72)
    pixmap = page.get_pixmap(matrix=matrix, clip=rect, alpha=False)
    pixmap.save(crop_path)


def render_crop_image(page: fitz.Page, rect: fitz.Rect, dpi: int) -> Image.Image:
    matrix = fitz.Matrix(dpi / 72, dpi / 72)
    pixmap = page.get_pixmap(matrix=matrix, clip=rect, alpha=False)
    return Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)


def detect_non_text_visual_rect(
    page: fitz.Page,
    question_rect: fitz.Rect,
    question_text: str,
    question_lines: list[TextLine],
    dpi: int,
) -> fitz.Rect | None:
    if "트리" not in question_text:
        return None

    visual_band = get_visual_band_from_lines(question_lines)
    if visual_band is None:
        return None
    stem_bottom, first_choice_top = visual_band

    clip = clamp_rect(
        fitz.Rect(
            question_rect.x0 - 8,
            stem_bottom + 2,
            question_rect.x1 + 8,
            first_choice_top - 2,
        ),
        page.rect,
    )
    if clip.is_empty or clip.y1 <= clip.y0:
        return None
    scale = dpi / 72
    pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=clip, alpha=False)
    image = Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)
    masked_image = image.copy()
    draw = ImageDraw.Draw(masked_image)

    for word in page.get_text("words"):
        word_rect = fitz.Rect(word[:4])
        intersection = clip & word_rect
        if intersection.is_empty:
            continue
        draw.rectangle(
            [
                (intersection.x0 - clip.x0) * scale - 3,
                (intersection.y0 - clip.y0) * scale - 3,
                (intersection.x1 - clip.x0) * scale + 3,
                (intersection.y1 - clip.y0) * scale + 3,
            ],
            fill="white",
        )

    grayscale = masked_image.convert("L")
    dark_bbox = grayscale.point(lambda pixel: 255 if pixel > 245 else 0).point(
        lambda pixel: 0 if pixel == 255 else 255
    ).getbbox()
    if dark_bbox is None:
        return None

    histogram = grayscale.histogram()
    dark_pixel_count = sum(histogram[:245])
    if dark_pixel_count < 2500:
        return None

    x0, y0, x1, y1 = dark_bbox
    visual_rect = fitz.Rect(
        clip.x0 + (x0 / scale),
        clip.y0 + (y0 / scale),
        clip.x0 + (x1 / scale),
        clip.y0 + (y1 / scale),
    )
    if visual_rect.width < 20 or visual_rect.height < 20:
        return None
    return clamp_rect(visual_rect, page.rect)


def refine_tree_crop_rect(page: fitz.Page, rect: fitz.Rect, dpi: int) -> fitz.Rect:
    scale = dpi / 72
    image = render_crop_image(page, rect, dpi)
    pixmap_width, pixmap_height = image.size
    grayscale = image.convert("L")
    binary = grayscale.point(lambda pixel: 0 if pixel < 245 else 255)
    cleaned = remove_edge_vertical_noise(binary)
    dark_bbox = get_non_edge_content_bbox(cleaned)
    if dark_bbox is None:
        dark_bbox = cleaned.point(lambda pixel: 255 if pixel > 0 else 0).point(
            lambda pixel: 0 if pixel == 255 else 255
        ).getbbox()
    if dark_bbox is None:
        return rect

    x0, y0, x1, y1 = dark_bbox
    padding_px = 6
    refined = fitz.Rect(
        rect.x0 + max(0, x0 - padding_px) / scale,
        rect.y0 + max(0, y0 - padding_px) / scale,
        rect.x0 + min(pixmap_width, x1 + padding_px) / scale,
        rect.y0 + min(pixmap_height, y1 + padding_px) / scale,
    )
    if refined.width < 20 or refined.height < 20:
        return rect
    return clamp_rect(refined, page.rect)


def remove_edge_vertical_noise(binary_image: Image.Image) -> Image.Image:
    width, height = binary_image.size
    pixels = binary_image.load()
    visited: set[tuple[int, int]] = set()
    cleaned = binary_image.copy()
    cleaned_pixels = cleaned.load()

    def is_dark(x: int, y: int) -> bool:
        return pixels[x, y] == 0

    for start_y in range(height):
        for start_x in (0, width - 1):
            if (start_x, start_y) in visited or not is_dark(start_x, start_y):
                continue

            queue = deque([(start_x, start_y)])
            component: list[tuple[int, int]] = []
            min_x = max_x = start_x
            min_y = max_y = start_y

            while queue:
                x, y = queue.popleft()
                if (x, y) in visited:
                    continue
                visited.add((x, y))
                if not is_dark(x, y):
                    continue

                component.append((x, y))
                min_x = min(min_x, x)
                max_x = max(max_x, x)
                min_y = min(min_y, y)
                max_y = max(max_y, y)

                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < width and 0 <= ny < height and (nx, ny) not in visited:
                        queue.append((nx, ny))

            if not component:
                continue

            component_width = max_x - min_x + 1
            component_height = max_y - min_y + 1
            touches_edge = min_x == 0 or max_x == width - 1
            looks_like_separator = (
                touches_edge and component_width <= 12 and component_height >= int(height * 0.4)
            )
            if not looks_like_separator:
                continue

            for x, y in component:
                cleaned_pixels[x, y] = 255

    return cleaned


def get_non_edge_content_bbox(binary_image: Image.Image) -> tuple[int, int, int, int] | None:
    width, height = binary_image.size
    pixels = binary_image.load()
    visited: set[tuple[int, int]] = set()
    kept_boxes: list[tuple[int, int, int, int]] = []

    for y in range(height):
        for x in range(width):
            if (x, y) in visited or pixels[x, y] != 0:
                continue

            queue = deque([(x, y)])
            min_x = max_x = x
            min_y = max_y = y
            count = 0
            touches_edge = False

            while queue:
                cx, cy = queue.popleft()
                if (cx, cy) in visited:
                    continue
                visited.add((cx, cy))
                if pixels[cx, cy] != 0:
                    continue

                count += 1
                min_x = min(min_x, cx)
                max_x = max(max_x, cx)
                min_y = min(min_y, cy)
                max_y = max(max_y, cy)
                if cx in (0, width - 1) or cy in (0, height - 1):
                    touches_edge = True

                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = cx + dx, cy + dy
                    if 0 <= nx < width and 0 <= ny < height and (nx, ny) not in visited:
                        queue.append((nx, ny))

            if count < 20 or touches_edge:
                continue
            kept_boxes.append((min_x, min_y, max_x + 1, max_y + 1))

    if not kept_boxes:
        return None

    return (
        min(box[0] for box in kept_boxes),
        min(box[1] for box in kept_boxes),
        max(box[2] for box in kept_boxes),
        max(box[3] for box in kept_boxes),
    )


def clean_tree_crop_image(image: Image.Image, threshold: int = 245) -> Image.Image:
    grayscale = image.convert("L")
    binary = grayscale.point(lambda pixel: 0 if pixel < threshold else 255)
    width, height = binary.size
    binary_pixels = binary.load()
    cleaned = image.copy()
    cleaned_pixels = cleaned.load()
    visited: set[tuple[int, int]] = set()

    for y in range(height):
        for x in range(width):
            if (x, y) in visited or binary_pixels[x, y] != 0:
                continue

            queue = deque([(x, y)])
            component: list[tuple[int, int]] = []
            touches_edge = False

            while queue:
                cx, cy = queue.popleft()
                if (cx, cy) in visited:
                    continue
                visited.add((cx, cy))
                if binary_pixels[cx, cy] != 0:
                    continue

                component.append((cx, cy))
                if cx in (0, width - 1) or cy in (0, height - 1):
                    touches_edge = True

                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = cx + dx, cy + dy
                    if 0 <= nx < width and 0 <= ny < height and (nx, ny) not in visited:
                        queue.append((nx, ny))

            if not component or not touches_edge:
                continue

            for cx, cy in component:
                cleaned_pixels[cx, cy] = (255, 255, 255)

    return cleaned


def should_crop_boxed_text(candidate_text: str) -> bool:
    if not candidate_text:
        return False

    boxed_markers = (
        "ㆍ",
        "SELECT ",
        "UPDATE ",
        "#include",
        "public class",
        "System.out",
        "while (",
        "for (",
        "JavaScript",
    )
    if any(marker in candidate_text for marker in boxed_markers):
        return True
    if NUMBER_LIST_RE.search(candidate_text):
        return True
    if len(candidate_text.splitlines()) >= 2:
        return True
    return False


def attach_boxed_text_crops(
    doc: fitz.Document,
    questions: list[dict[str, object]],
    out_dir: Path,
    dpi: int,
    crop_index_start: int = 1,
) -> list[dict[str, object]]:
    image_crops: list[dict[str, object]] = []
    crop_index = crop_index_start

    def append_crop(question: dict[str, object], page_number: int, clipped: fitz.Rect) -> None:
        nonlocal crop_index

        crop_name = f"crop_id{crop_index:04d}_p{page_number}.png"
        relative_crop_path = Path("crops") / crop_name
        absolute_crop_path = out_dir / relative_crop_path
        save_crop(doc[page_number - 1], clipped, absolute_crop_path, dpi)

        image_entry = {
            "type": "image",
            "element_id": crop_index,
            "page_number": page_number,
            "bounding_box": [round(value, 3) for value in clipped],
            "source": str(relative_crop_path).replace("\\", "/"),
            "crop_path": str(relative_crop_path).replace("\\", "/"),
        }
        question["images"].append(image_entry)
        image_crops.append(
            {
                "element_id": crop_index,
                "page_number": page_number,
                "type": "image",
                "bounding_box": [round(value, 3) for value in clipped],
                "crop_path": str(relative_crop_path).replace("\\", "/"),
            }
        )
        crop_index += 1

    for question in questions:
        page_number = int(question["page_number"])
        page = doc[page_number - 1]
        question_rect = fitz.Rect(merge_bboxes(line.bbox for line in question["raw_lines"]))
        expanded_rect = fitz.Rect(
            question_rect.x0 - 8,
            question_rect.y0 - 12,
            question_rect.x1 + 8,
            question_rect.y1 + 12,
        )

        for rect_like in page.cluster_drawings():
            candidate = fitz.Rect(rect_like)
            center_x = (candidate.x0 + candidate.x1) / 2
            center_y = (candidate.y0 + candidate.y1) / 2
            if not rect_contains(expanded_rect, center_x, center_y):
                continue

            matched_indexes: list[int] = []
            matched_texts: list[str] = []
            for index, line in enumerate(question["raw_lines"]):
                line_center_x = (line.bbox[0] + line.bbox[2]) / 2
                line_center_y = (line.bbox[1] + line.bbox[3]) / 2
                if not rect_contains(candidate, line_center_x, line_center_y):
                    continue
                if is_question_start_line(line.text) or is_choice_line(line.text):
                    continue
                matched_indexes.append(index)
                matched_texts.append(line.text)

            if not matched_indexes:
                continue

            candidate_text = "\n".join(matched_texts)
            if not should_crop_boxed_text(candidate_text):
                continue

            question["excluded_line_indexes"].update(matched_indexes)
            append_crop(question, page_number, clamp_rect(candidate, page.rect))

    return image_crops


def attach_visual_crops(
    doc: fitz.Document,
    questions: list[dict[str, object]],
    out_dir: Path,
    dpi: int,
    crop_index_start: int = 1,
) -> list[dict[str, object]]:
    image_crops: list[dict[str, object]] = []
    candidates_by_page = collect_visual_candidates(doc)
    crop_index = crop_index_start

    def append_crop(
        question: dict[str, object],
        page_number: int,
        clipped: fitz.Rect,
        *,
        clean_tree_noise: bool = False,
    ) -> None:
        nonlocal crop_index

        crop_name = f"crop_id{crop_index:04d}_p{page_number}.png"
        relative_crop_path = Path("crops") / crop_name
        absolute_crop_path = out_dir / relative_crop_path
        if clean_tree_noise:
            image = render_crop_image(doc[page_number - 1], clipped, dpi)
            image = clean_tree_crop_image(image)
            absolute_crop_path.parent.mkdir(parents=True, exist_ok=True)
            image.save(absolute_crop_path)
        else:
            save_crop(doc[page_number - 1], clipped, absolute_crop_path, dpi)

        image_entry = {
            "type": "image",
            "element_id": crop_index,
            "page_number": page_number,
            "bounding_box": [round(value, 3) for value in clipped],
            "source": str(relative_crop_path).replace("\\", "/"),
            "crop_path": str(relative_crop_path).replace("\\", "/"),
        }
        question["images"].append(image_entry)
        image_crops.append(
            {
                "element_id": crop_index,
                "page_number": page_number,
                "type": "image",
                "bounding_box": [round(value, 3) for value in clipped],
                "crop_path": str(relative_crop_path).replace("\\", "/"),
            }
        )
        crop_index += 1

    for question in questions:
        page_number = int(question["page_number"])
        page = doc[page_number - 1]
        question_rect = fitz.Rect(merge_bboxes(line.bbox for line in question["raw_lines"]))
        expanded_rect = fitz.Rect(
            question_rect.x0 - 8,
            question_rect.y0 - 12,
            question_rect.x1 + 8,
            question_rect.y1 + 12,
        )
        page_rect = page.rect
        current_question_text, _ = parse_choice_text(
            normalize_text(" ".join(line.text for line in get_included_lines(question)))
        )
        is_tree_question = "트리" in current_question_text

        if question["images"]:
            continue

        if not is_tree_question:
            for candidate in candidates_by_page.get(page_number, []):
                center_x = (candidate.x0 + candidate.x1) / 2
                center_y = (candidate.y0 + candidate.y1) / 2
                if not rect_contains(expanded_rect, center_x, center_y):
                    continue
                if is_text_representable_visual(current_question_text):
                    continue

                clipped = clamp_rect(candidate, page_rect)
                append_crop(question, page_number, clipped)

        if question["images"]:
            continue

        fallback_rect = detect_non_text_visual_rect(
            page=page,
            question_rect=question_rect,
            question_text=current_question_text,
            question_lines=get_included_lines(question),
            dpi=dpi,
        )
        if fallback_rect is not None:
            fallback_rect = refine_tree_crop_rect(page, fallback_rect, dpi)
            append_crop(question, page_number, fallback_rect, clean_tree_noise=True)

    return image_crops


def parse_test1_pdf(pdf_path: Path, out_dir: Path | None = None, dpi: int = 150) -> dict[str, object]:
    pdf_path = Path(pdf_path)
    if out_dir is None:
        out_dir = Path("new") / "output" / pdf_path.stem
    out_dir.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(pdf_path)
    page_count = doc.page_count
    try:
        lines = extract_ordered_lines(doc)
        questions = build_questions(lines)
        image_crops = attach_boxed_text_crops(doc, questions, out_dir, dpi)
        image_crops.extend(
            attach_visual_crops(
                doc,
                questions,
                out_dir,
                dpi,
                crop_index_start=len(image_crops) + 1,
            )
        )
        questions = [finalize_question(question) for question in questions]
    finally:
        doc.close()

    result = {
        "source": pdf_path.name,
        "questions": questions,
        "image_crops": image_crops,
        "metadata": {
            "total_questions": len(questions),
            "pages": page_count,
            "generated_image_crops": len(image_crops),
        },
    }
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="data/test-1.pdf 전용 문제/선택지 JSON 추출")
    parser.add_argument("--pdf", type=Path, default=Path("data/test-1.pdf"), help="입력 PDF 경로")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="출력 디렉터리 (기본: new/output/<pdf이름>)",
    )
    parser.add_argument("--dpi", type=int, default=150, help="crop 렌더 DPI")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = args.output_dir or (Path("new") / "output" / args.pdf.stem)
    result = parse_test1_pdf(args.pdf, out_dir=output_dir, dpi=args.dpi)
    json_path = output_dir / f"{args.pdf.stem}_questions.json"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json_path)


if __name__ == "__main__":
    main()
