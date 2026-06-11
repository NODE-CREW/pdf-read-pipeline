#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
What it does:
- PDF 각 페이지를 PNG로 렌더링
- 렌더링된 이미지를 포함한 .tex 파일 생성
- 각 문항 텍스트를 "문제"와 "선택지"로 분리해 txt 파일 저장
- 각 문항 이미지를 "문제"와 "선택지"로 분리해 PNG 저장

Note:
- 루트 실행 스크립트에서 내부화한 legacy 구현입니다.
- 외부 실행 진입점으로 사용하지 않고 `pipelines.base`에서 동적으로 로드합니다.

왜 이 방식인가:
- 폰트 인코딩 문제로 텍스트 추출 시 수식이 깨질 수 있음 (예: PUA glyph)
- 이미지 기반 LaTeX는 수식 모양을 원본 그대로 확인 가능
"""

from __future__ import annotations

import argparse
import os
import re
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple


QUESTION_START_RE = re.compile(
    r"""
    ^\s*
    (?:
        (?:문\s*\d+)|
        (?:제\s*\d+\s*문)|
        (?:\d+\s*번)|
        (?:\d+\s*[\.\)])
    )
    \s*
    """,
    re.VERBOSE,
)
QUESTION_START_BODY_RE = re.compile(r"[0-9A-Za-z가-힣]")

CHOICE_LINE_RE = re.compile(r"^\s*[①②③④⑤⑥⑦⑧⑨⑩]\s*")
ALT_CHOICE_RE = re.compile(r"^\s*\(\s*[1-5]\s*\)\s*")


@dataclass
class QuestionStart:
    page_index: int
    column: int
    y0: float
    qno: Optional[int]


@dataclass
class QuestionSpanSegment:
    page_index: int
    column: int
    start_y: float
    end_y: float


@dataclass
class QuestionSpan:
    index: int
    qno: Optional[int]
    segments: List[QuestionSpanSegment]


@dataclass
class QuestionImageSet:
    index: int
    qno: Optional[int]
    problem_image_paths: List[str]
    choices_image_paths: List[str]


@dataclass
class QuestionTextSet:
    index: int
    qno: Optional[int]
    question_text: str
    choices_text: str


def escape_latex_text(text: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "{": r"\{",
        "}": r"\}",
        "#": r"\#",
        "$": r"\$",
        "%": r"\%",
        "&": r"\&",
        "_": r"\_",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(ch, ch) for ch in text)


def split_question_and_choices(question_text: str) -> Tuple[str, str]:
    lines = question_text.splitlines()
    first_choice_idx: Optional[int] = None
    for idx, line in enumerate(lines):
        if CHOICE_LINE_RE.match(line) or ALT_CHOICE_RE.match(line):
            first_choice_idx = idx
            break

    if first_choice_idx is None:
        return question_text.strip(), ""

    problem = "\n".join(lines[:first_choice_idx]).strip()
    choices = "\n".join(lines[first_choice_idx:]).strip()
    return problem, choices


def parse_question_number(text: str) -> Optional[int]:
    num_m = re.search(r"(\d+)", text)
    if not num_m:
        return None
    try:
        return int(num_m.group(1))
    except ValueError:
        return None


def is_reasonable_question_number(qno: Optional[int]) -> bool:
    if qno is None:
        return False
    return 1 <= qno <= 100


def is_valid_question_start_line(text: str) -> bool:
    if not text:
        return False

    match = QUESTION_START_RE.match(text)
    if match is None:
        return False

    qno = parse_question_number(text)
    if not is_reasonable_question_number(qno):
        return False

    remainder = text[match.end():].strip()
    if not remainder:
        return False

    # 수식 꼬리 조각 같은 "1)))}" 류를 문항 시작으로 오탐하지 않도록
    # 접두부 뒤에는 실제 본문을 나타내는 문자/숫자가 최소 한 개 있어야 한다.
    return QUESTION_START_BODY_RE.search(remainder) is not None


def should_render_segment(part_index: int, segment_height: float) -> bool:
    if segment_height <= 4.0:
        return False
    # 이어지는 조각(part>=2)은 너무 얇으면 대부분 노이즈이므로 제외
    if part_index >= 2 and segment_height < 150.0:
        return False
    return True


def compute_raw_clip_bounds(
    segment_start_y: float,
    segment_end_y: float,
    page_height: float,
    part_index: int,
    top_padding: float,
    boundary_gap: float,
    footer_margin: float,
) -> tuple[float, float]:
    raw_y0 = max(0.0, segment_start_y - top_padding)
    raw_y1 = min(page_height, segment_end_y - boundary_gap)

    # 첫 조각은 이전 문항 꼬리 글자가 섞이지 않도록 시작선보다 위를 허용하지 않는다.
    if part_index == 1:
        raw_y0 = max(raw_y0, segment_start_y + 1.0)

    # 페이지 끝까지 가는 세그먼트는 푸터/하단 구분선 영역을 제외한다.
    if segment_end_y >= page_height - 1.0:
        raw_y1 = min(raw_y1, max(raw_y0 + 5.0, page_height - footer_margin))

    return raw_y0, raw_y1


def normalize_two_columns(columns: List[tuple[float, float]]) -> List[tuple[float, float]]:
    if len(columns) != 2:
        return columns
    left, right = sorted(columns, key=lambda c: c[0])
    if left[1] < right[0]:
        return [left, right]

    split_x = (left[1] + right[0]) / 2.0
    gap = 2.0
    left_fixed = (left[0], max(left[0], split_x - gap))
    right_fixed = (min(right[1], split_x + gap), right[1])
    return [left_fixed, right_fixed]


def expand_column_bounds(
    columns: List[tuple[float, float]],
    column_index: int,
    page_width: float,
    margin: float = 18.0,
    gap_guard: float = 2.0,
) -> tuple[float, float]:
    x0, x1 = columns[column_index]
    expanded_x0 = max(0.0, x0 - margin)
    expanded_x1 = min(page_width, x1 + margin)

    if column_index > 0:
        prev_x1 = columns[column_index - 1][1]
        expanded_x0 = max(expanded_x0, prev_x1 + gap_guard)
    if column_index < len(columns) - 1:
        next_x0 = columns[column_index + 1][0]
        expanded_x1 = min(expanded_x1, next_x0 - gap_guard)

    if expanded_x1 <= expanded_x0 + 4.0:
        return x0, x1
    return expanded_x0, expanded_x1


def refine_clip_y_to_text_blocks(
    raw_y0: float,
    raw_y1: float,
    text_block_boxes: List[tuple[float, float, float, float]],
) -> tuple[float, float]:
    if not text_block_boxes:
        return raw_y0, raw_y1

    text_y0 = min(y0 for _, y0, _, _ in text_block_boxes)
    text_y1 = max(y1 for _, _, _, y1 in text_block_boxes)

    pad = 3.0
    refined_y0 = max(raw_y0, text_y0 - pad)
    refined_y1 = min(raw_y1, text_y1 + pad)

    if refined_y1 <= refined_y0 + 4.0:
        return raw_y0, raw_y1
    return refined_y0, refined_y1


def refine_clip_x_to_text_blocks(
    raw_x0: float,
    raw_x1: float,
    text_block_boxes: List[tuple[float, float, float, float]],
) -> tuple[float, float]:
    if not text_block_boxes:
        return raw_x0, raw_x1

    text_x0 = min(x0 for x0, _, _, _ in text_block_boxes)
    text_x1 = max(x1 for _, _, x1, _ in text_block_boxes)

    # 블록 bbox 오차로 문장 우측 끝이 잘리는 경우를 막기 위해
    # 여백이 충분히 큰 경우에만 x축을 줄인다.
    pad = 12.0
    trim_threshold = 24.0

    refined_x0 = raw_x0
    refined_x1 = raw_x1

    if (text_x0 - raw_x0) > trim_threshold:
        refined_x0 = max(raw_x0, text_x0 - pad)
    if (raw_x1 - text_x1) > trim_threshold:
        refined_x1 = min(raw_x1, text_x1 + pad)

    if refined_x1 <= refined_x0 + 4.0:
        return raw_x0, raw_x1
    return refined_x0, refined_x1


def collect_text_blocks_for_clip(page, clip_x0: float, clip_x1: float, raw_y0: float, raw_y1: float):
    text_dict = page.get_text("dict", sort=True)
    boxes: List[tuple[float, float, float, float]] = []
    for block in text_dict.get("blocks", []):
        if block.get("type") != 0:
            continue
        x0, y0, x1, y1 = [float(v) for v in block.get("bbox", [0, 0, 0, 0])]
        if x1 <= x0 or y1 <= y0:
            continue

        x_overlap = min(x1, clip_x1) - max(x0, clip_x0)
        y_overlap = min(y1, raw_y1) - max(y0, raw_y0)
        if x_overlap <= 0 or y_overlap <= 0:
            continue

        # 인접 컬럼 블록 오탐을 줄이기 위해 블록 폭 대비 겹침 비율 최소치 적용
        if x_overlap / (x1 - x0) < 0.3:
            continue

        boxes.append((x0, y0, x1, y1))
    return boxes


def infer_columns_from_ranges(
    block_ranges: List[tuple[float, float]],
    page_width: float,
) -> List[tuple[float, float]]:
    if len(block_ranges) < 4:
        return [(0.0, page_width)]

    centers = sorted((x0 + x1) / 2.0 for x0, x1 in block_ranges)
    max_gap = 0.0
    max_gap_idx = 0
    for i in range(len(centers) - 1):
        gap = centers[i + 1] - centers[i]
        if gap > max_gap:
            max_gap = gap
            max_gap_idx = i

    if max_gap < page_width * 0.18:
        return [(0.0, page_width)]

    split_x = (centers[max_gap_idx] + centers[max_gap_idx + 1]) / 2.0
    left = [(x0, x1) for x0, x1 in block_ranges if (x0 + x1) / 2.0 <= split_x]
    right = [(x0, x1) for x0, x1 in block_ranges if (x0 + x1) / 2.0 > split_x]
    if len(left) < 2 or len(right) < 2:
        return [(0.0, page_width)]

    pad = 4.0
    left_x0 = max(0.0, min(x0 for x0, _ in left) - pad)
    left_x1 = min(page_width, max(x1 for _, x1 in left) + pad)
    right_x0 = max(0.0, min(x0 for x0, _ in right) - pad)
    right_x1 = min(page_width, max(x1 for _, x1 in right) + pad)

    return normalize_two_columns([(left_x0, left_x1), (right_x0, right_x1)])


def detect_page_columns(doc) -> List[List[tuple[float, float]]]:
    page_columns: List[List[tuple[float, float]]] = []
    page_widths: List[float] = []

    for page in doc:
        page_width = float(page.rect.width)
        page_widths.append(page_width)
        text_dict = page.get_text("dict", sort=True)
        ranges: List[tuple[float, float]] = []
        for block in text_dict.get("blocks", []):
            if block.get("type") != 0:
                continue
            x0, _, x1, _ = block.get("bbox", [0, 0, 0, 0])
            if x1 > x0:
                ranges.append((float(x0), float(x1)))
        page_columns.append(infer_columns_from_ranges(ranges, page_width=page_width))

    # 일부 페이지에서 헤더/노이즈 때문에 단일 컬럼으로 오판하는 경우, 다수 페이지의 2단 정보를 재사용.
    two_col_pages = [cols for cols in page_columns if len(cols) == 2]
    if len(two_col_pages) >= 2:
        template = [
            (
                float(statistics.median([cols[0][0] for cols in two_col_pages])),
                float(statistics.median([cols[0][1] for cols in two_col_pages])),
            ),
            (
                float(statistics.median([cols[1][0] for cols in two_col_pages])),
                float(statistics.median([cols[1][1] for cols in two_col_pages])),
            ),
        ]
        for i, columns in enumerate(page_columns):
            if len(columns) == 1:
                width = page_widths[i]
                page_columns[i] = [
                    (max(0.0, min(width, x0)), max(0.0, min(width, x1)))
                    for x0, x1 in template
                ]
                page_columns[i] = normalize_two_columns(page_columns[i])
            elif len(columns) == 2:
                page_columns[i] = normalize_two_columns(columns)

    return page_columns


def find_column_index(x_center: float, columns: List[tuple[float, float]]) -> int:
    if len(columns) <= 1:
        return 0
    distances = [abs((x0 + x1) / 2.0 - x_center) for x0, x1 in columns]
    return min(range(len(distances)), key=lambda i: distances[i])


def get_question_starts(doc, page_columns: List[List[tuple[float, float]]]) -> List[QuestionStart]:
    starts: List[QuestionStart] = []
    for page_idx, page in enumerate(doc):
        text_dict = page.get_text("dict", sort=True)
        for block in text_dict.get("blocks", []):
            if block.get("type") != 0:
                continue

            for line in block.get("lines", []):
                spans = line.get("spans", [])
                span_text = "".join(span.get("text", "") for span in spans)
                span_text = span_text.strip()
                if not is_valid_question_start_line(span_text):
                    continue

                qno = parse_question_number(span_text)

                if spans:
                    x0 = float(spans[0].get("bbox", [0, 0, 0, 0])[0])
                    x1 = float(spans[-1].get("bbox", [0, 0, 0, 0])[2])
                else:
                    x0, _, x1, _ = line.get("bbox", [0, 0, 0, 0])

                y0 = float(line.get("bbox", [0, 0, 0, 0])[1])
                x_center = (float(x0) + float(x1)) / 2.0
                column = find_column_index(x_center, page_columns[page_idx])

                starts.append(
                    QuestionStart(
                        page_index=page_idx,
                        column=column,
                        y0=y0,
                        qno=qno,
                    )
                )
                continue

    starts.sort(key=lambda x: (x.page_index, x.column, x.y0))
    return starts


def build_question_spans(
    starts: List[QuestionStart],
    page_heights: List[float],
    page_columns: List[List[tuple[float, float]]],
) -> List[QuestionSpan]:
    if not starts:
        return []

    spans: List[QuestionSpan] = []
    for idx, start in enumerate(starts, start=1):
        nxt = starts[idx] if idx < len(starts) else None
        segments: List[QuestionSpanSegment] = []

        if nxt is not None:
            for page_idx in range(start.page_index, nxt.page_index + 1):
                col_count = len(page_columns[page_idx])
                start_col = start.column if page_idx == start.page_index else 0
                end_col = nxt.column if page_idx == nxt.page_index else col_count - 1

                for col in range(start_col, end_col + 1):
                    seg_start_y = start.y0 if (page_idx == start.page_index and col == start.column) else 0.0
                    if page_idx == nxt.page_index and col == nxt.column:
                        seg_end_y = nxt.y0
                    else:
                        seg_end_y = page_heights[page_idx]

                    if seg_end_y > seg_start_y + 4.0:
                        segments.append(
                            QuestionSpanSegment(
                                page_index=page_idx,
                                column=col,
                                start_y=seg_start_y,
                                end_y=seg_end_y,
                            )
                        )
        else:
            for page_idx in range(start.page_index, len(page_heights)):
                col_count = len(page_columns[page_idx])
                start_col = start.column if page_idx == start.page_index else 0
                for col in range(start_col, col_count):
                    seg_start_y = start.y0 if (page_idx == start.page_index and col == start.column) else 0.0
                    seg_end_y = page_heights[page_idx]
                    if seg_end_y > seg_start_y + 4.0:
                        segments.append(
                            QuestionSpanSegment(
                                page_index=page_idx,
                                column=col,
                                start_y=seg_start_y,
                                end_y=seg_end_y,
                            )
                        )

        spans.append(QuestionSpan(index=idx, qno=start.qno, segments=segments))

    return spans


def render_pdf_pages_to_png(doc, image_dir: str, dpi: int = 200) -> List[str]:
    import fitz

    image_dir_path = Path(image_dir)
    image_dir_path.mkdir(parents=True, exist_ok=True)

    rendered_paths: List[str] = []
    scale = dpi / 72.0
    matrix = fitz.Matrix(scale, scale)

    for idx, page in enumerate(doc, start=1):
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        out_path = image_dir_path / f"page_{idx:03d}.png"
        pix.save(out_path)
        rendered_paths.append(str(out_path))

    return rendered_paths


def save_split_texts(out_dir: Path | str, question_texts: List[QuestionTextSet]) -> None:
    out_dir_path = Path(out_dir)
    out_dir_path.mkdir(parents=True, exist_ok=True)

    for item in question_texts:
        q_path = out_dir_path / f"question_{item.index:03d}_problem.txt"
        c_path = out_dir_path / f"question_{item.index:03d}_choices.txt"
        q_path.write_text(item.question_text, encoding="utf-8")
        c_path.write_text(item.choices_text, encoding="utf-8")


def split_problem_and_choices_clip_by_choice_blocks(
    clip_y0: float,
    clip_y1: float,
    text_blocks: List[tuple[float, float, str]],
) -> tuple[Optional[tuple[float, float]], Optional[tuple[float, float]]]:
    choice_starts: List[float] = []

    for block_y0, _, block_text in text_blocks:
        for line in block_text.splitlines():
            if CHOICE_LINE_RE.match(line) or ALT_CHOICE_RE.match(line):
                choice_starts.append(max(clip_y0, block_y0))
                break

    if not choice_starts:
        return (clip_y0, clip_y1), None

    split_y = min(choice_starts)
    problem_end = min(clip_y1, split_y - 1.0)
    choices_start = max(clip_y0, split_y)

    problem_clip: Optional[tuple[float, float]]
    choices_clip: Optional[tuple[float, float]]
    problem_clip = (clip_y0, problem_end) if problem_end > clip_y0 + 4.0 else None
    choices_clip = (choices_start, clip_y1) if clip_y1 > choices_start + 4.0 else None

    if problem_clip is None and choices_clip is None:
        return (clip_y0, clip_y1), None
    return problem_clip, choices_clip


def _render_pdf_questions_with_text(
    pdf_path: str,
    image_dir: str,
    dpi: int = 200,
) -> tuple[List[QuestionImageSet], List[QuestionTextSet]]:
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError(
            "PyMuPDF(fitz)가 필요합니다. 설치: python -m pip install pymupdf"
        ) from exc

    image_dir_path = Path(image_dir)
    image_dir_path.mkdir(parents=True, exist_ok=True)
    scale = dpi / 72.0
    matrix = fitz.Matrix(scale, scale)
    top_padding = 1.0
    boundary_gap = 2.0
    footer_margin = 70.0

    with fitz.open(pdf_path) as doc:
        page_columns = detect_page_columns(doc)
        page_heights = [float(page.rect.height) for page in doc]
        starts = get_question_starts(doc, page_columns=page_columns)
        spans = build_question_spans(starts, page_heights, page_columns=page_columns)

        if not spans:
            # 문항 시작점을 못 잡으면 페이지 단위 fallback
            page_images = render_pdf_pages_to_png(doc, image_dir=image_dir, dpi=dpi)
            question_images = [
                QuestionImageSet(
                    index=i + 1,
                    qno=None,
                    problem_image_paths=[path],
                    choices_image_paths=[],
                )
                for i, path in enumerate(page_images)
            ]
            question_texts: List[QuestionTextSet] = []
            for i, page in enumerate(doc, start=1):
                raw_text = (page.get_text("text") or "").strip()
                question_text, choices_text = split_question_and_choices(raw_text)
                question_texts.append(
                    QuestionTextSet(
                        index=i,
                        qno=None,
                        question_text=question_text,
                        choices_text=choices_text,
                    )
                )
            return question_images, question_texts

        question_images: List[QuestionImageSet] = []
        question_texts: List[QuestionTextSet] = []
        for span in spans:
            problem_paths: List[str] = []
            choices_paths: List[str] = []
            extracted_text_parts: List[str] = []
            segment_part = 1
            problem_part = 1
            choices_part = 1
            for segment in span.segments:
                page = doc.load_page(segment.page_index)
                page_width = float(page.rect.width)
                page_height = float(page.rect.height)
                col_x0, col_x1 = expand_column_bounds(
                    columns=page_columns[segment.page_index],
                    column_index=segment.column,
                    page_width=page_width,
                )

                raw_y0, raw_y1 = compute_raw_clip_bounds(
                    segment_start_y=segment.start_y,
                    segment_end_y=segment.end_y,
                    page_height=page_height,
                    part_index=segment_part,
                    top_padding=top_padding,
                    boundary_gap=boundary_gap,
                    footer_margin=footer_margin,
                )
                clip_x0 = max(0.0, col_x0)
                clip_x1 = min(page_width, col_x1)

                text_boxes = collect_text_blocks_for_clip(
                    page=page,
                    clip_x0=clip_x0,
                    clip_x1=clip_x1,
                    raw_y0=raw_y0,
                    raw_y1=raw_y1,
                )
                y0, y1 = refine_clip_y_to_text_blocks(
                    raw_y0=raw_y0,
                    raw_y1=raw_y1,
                    text_block_boxes=text_boxes,
                )
                clip_x0, clip_x1 = refine_clip_x_to_text_blocks(
                    raw_x0=clip_x0,
                    raw_x1=clip_x1,
                    text_block_boxes=text_boxes,
                )

                segment_height = y1 - y0
                if not should_render_segment(part_index=segment_part, segment_height=segment_height):
                    continue

                clip = fitz.Rect(clip_x0, y0, clip_x1, y1)
                clip_text = (page.get_text("text", clip=clip) or "").strip()
                if clip_text:
                    extracted_text_parts.append(clip_text)

                block_rows = page.get_text("blocks", clip=clip, sort=True)
                text_blocks_for_split: List[tuple[float, float, str]] = []
                for row in block_rows:
                    if len(row) < 5:
                        continue
                    bx0, by0, bx1, by1, btext = row[0], row[1], row[2], row[3], row[4]
                    if bx1 <= bx0 or by1 <= by0:
                        continue
                    text_blocks_for_split.append((float(by0), float(by1), str(btext or "")))

                problem_clip_y, choices_clip_y = split_problem_and_choices_clip_by_choice_blocks(
                    clip_y0=y0,
                    clip_y1=y1,
                    text_blocks=text_blocks_for_split,
                )

                if problem_clip_y is not None:
                    problem_clip = fitz.Rect(clip_x0, problem_clip_y[0], clip_x1, problem_clip_y[1])
                    pix = page.get_pixmap(matrix=matrix, clip=problem_clip, alpha=False)
                    out_path = image_dir_path / (
                        f"question_{span.index:03d}_problem_part_{problem_part:02d}.png"
                    )
                    pix.save(out_path)
                    problem_paths.append(str(out_path))
                    problem_part += 1

                if choices_clip_y is not None:
                    choices_clip = fitz.Rect(clip_x0, choices_clip_y[0], clip_x1, choices_clip_y[1])
                    pix = page.get_pixmap(matrix=matrix, clip=choices_clip, alpha=False)
                    out_path = image_dir_path / (
                        f"question_{span.index:03d}_choices_part_{choices_part:02d}.png"
                    )
                    pix.save(out_path)
                    choices_paths.append(str(out_path))
                    choices_part += 1

                segment_part += 1

            if problem_paths or choices_paths:
                sequence_index = len(question_images) + 1
                merged_text = "\n".join(extracted_text_parts).strip()
                question_text, choices_text = split_question_and_choices(merged_text)
                question_images.append(
                    QuestionImageSet(
                        index=sequence_index,
                        qno=span.qno,
                        problem_image_paths=problem_paths,
                        choices_image_paths=choices_paths,
                    )
                )
                question_texts.append(
                    QuestionTextSet(
                        index=sequence_index,
                        qno=span.qno,
                        question_text=question_text,
                        choices_text=choices_text,
                    )
                )

    return question_images, question_texts


def render_pdf_questions_to_png(pdf_path: str, image_dir: str, dpi: int = 200) -> List[QuestionImageSet]:
    question_images, _ = _render_pdf_questions_with_text(pdf_path=pdf_path, image_dir=image_dir, dpi=dpi)
    return question_images


def build_latex_document(pdf_name: str, question_images: List[QuestionImageSet]) -> str:
    lines: List[str] = [
        r"\documentclass[11pt,a4paper]{article}",
        r"\usepackage[utf8]{inputenc}",
        r"\usepackage[T1]{fontenc}",
        r"\usepackage{graphicx}",
        r"\usepackage[margin=1in]{geometry}",
        r"\usepackage{float}",
        r"\title{PDF to LaTeX (Image-based)}",
        rf"\author{{Source: {escape_latex_text(pdf_name)}}}",
        r"\date{}",
        r"\begin{document}",
        r"\maketitle",
        r"",
    ]

    for item in question_images:
        if item.qno is None:
            section_title = rf"\section*{{Question {item.index}}}"
        else:
            section_title = rf"\section*{{Question {item.index} (No. {item.qno})}}"

        lines.append(section_title)
        if item.problem_image_paths:
            lines.append(r"\subsection*{Problem}")
        for rel_path in item.problem_image_paths:
            latex_path = rel_path.replace(os.sep, "/")
            lines.extend(
                [
                    r"\begin{figure}[H]",
                    r"\centering",
                    rf"\includegraphics[width=\textwidth]{{{latex_path}}}",
                    r"\end{figure}",
                    r"",
                ]
            )
        if item.choices_image_paths:
            lines.append(r"\subsection*{Choices}")
        for rel_path in item.choices_image_paths:
            latex_path = rel_path.replace(os.sep, "/")
            lines.extend(
                [
                    r"\begin{figure}[H]",
                    r"\centering",
                    rf"\includegraphics[width=\textwidth]{{{latex_path}}}",
                    r"\end{figure}",
                    r"",
                ]
            )

    lines.append(r"\end{document}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", required=True, help="PDF file path")
    parser.add_argument(
        "--out-tex",
        default="./output/output.tex",
        help="Output .tex path (default: ./output/output.tex)",
    )
    parser.add_argument(
        "--image-dir",
        default="./output/latex_pages",
        help="Directory to save rendered PNG pages (default: ./output/latex_pages)",
    )
    parser.add_argument(
        "--split-text-dir",
        default="./output/question_texts",
        help="Directory to save split question/choices text files (default: ./output/question_texts)",
    )
    parser.add_argument("--dpi", type=int, default=200, help="Render DPI (default: 200)")
    args = parser.parse_args()

    if not os.path.exists(args.pdf):
        raise FileNotFoundError(f"PDF not found: {args.pdf}")

    question_images, question_texts = _render_pdf_questions_with_text(
        args.pdf, args.image_dir, dpi=args.dpi
    )
    out_tex_path = Path(args.out_tex)
    out_tex_path.parent.mkdir(parents=True, exist_ok=True)

    # tex 파일 기준 상대경로로 이미지 경로를 저장
    question_images_for_tex = []
    for item in question_images:
        problem_rel_paths = [
            os.path.relpath(path, start=out_tex_path.parent) for path in item.problem_image_paths
        ]
        choices_rel_paths = [
            os.path.relpath(path, start=out_tex_path.parent) for path in item.choices_image_paths
        ]
        question_images_for_tex.append(
            QuestionImageSet(
                index=item.index,
                qno=item.qno,
                problem_image_paths=problem_rel_paths,
                choices_image_paths=choices_rel_paths,
            )
        )

    latex_content = build_latex_document(
        pdf_name=Path(args.pdf).name,
        question_images=question_images_for_tex,
    )
    out_tex_path.write_text(latex_content, encoding="utf-8")
    save_split_texts(args.split_text_dir, question_texts)

    print(f"Saved LaTeX: {out_tex_path}")
    print(f"Rendered question blocks: {len(question_images)}")
    print(f"Image dir: {Path(args.image_dir)}")
    print(f"Split text dir: {Path(args.split_text_dir)}")
    print(
        "Compile example: "
        f"pdflatex -interaction=nonstopmode -output-directory {out_tex_path.parent} {out_tex_path}"
    )


if __name__ == "__main__":
    main()
