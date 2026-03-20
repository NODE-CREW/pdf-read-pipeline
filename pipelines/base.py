#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Usage:
  python ./6_extract_all_text_and_save_latex_split_images.py

What it does:
- GUI 파일 선택기로 여러 PDF를 선택
- 각 PDF마다 output/<pdf파일명>/ 하위에 결과 저장
  - output.tex
  - latex_pages/*.png
  - question_texts/*.txt
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List


OUTPUT_ROOT = Path("./output")
REPO_ROOT = Path(__file__).resolve().parent.parent
SHARED_PASSAGE_RE = re.compile(
    r"\[\s*(\d{1,3})\s*[~\-]\s*(\d{1,3})\s*\]\s*다음\s*글을\s*읽고\s*물음에\s*답하시오\.?",
)
_PIL_IMAGE_AVAILABLE: bool | None = None
_OCR_WARNED_KEYS: set[str] = set()
OCR_QUESTION_START_RE = re.compile(r"^\s*(\d{1,3})\s*[\.\)]\s*")
OCR_QUESTION_START_SLASH7_RE = re.compile(r"^\s*/\s*[\.\)]\s*")
OCR_CHOICE_LINE_RE = re.compile(
    r"""
    ^\s*
    (?:
        [①②③④⑤⑥⑦⑧⑨⑩]|
        \(\s*[1-5]\s*\)|
        [1-5]\s*[\.\)]|
        [@©○●◦•※]|
        [A-Ea-e]\s*[\.\)]
    )
    \s*
    """,
    re.VERBOSE,
)
PAGE_TOP_NOISE_PATTERNS = (
    re.compile(r"컴퓨터활용능력"),
    re.compile(r"기출문제"),
    re.compile(r"전자문제집\s*CBT"),
    re.compile(r"www\.comcbt\.com", re.IGNORECASE),
)
PAGE_BOTTOM_NOISE_PATTERNS = (
    re.compile(r"^\s*\d+\s*과목\s*:\s*"),
    re.compile(r"최강\s*자격증.*전자문제집\s*CBT", re.IGNORECASE),
    re.compile(r"www\.comcbt\.com", re.IGNORECASE),
)


@dataclass
class SharedPassageSet:
    passage_id: str
    start_qno: int
    end_qno: int
    text: str
    image_paths: List[str]


def _normalize_block_text(text: str) -> str:
    return " ".join((text or "").split())


def _is_top_page_noise_block(
    text: str,
    *,
    y0: float,
    y1: float,
) -> bool:
    normalized = _normalize_block_text(text)
    if not normalized:
        return False
    if y0 > 48.0 and y1 > 56.0:
        return False
    return any(pattern.search(normalized) for pattern in PAGE_TOP_NOISE_PATTERNS)


def _is_bottom_page_noise_block(
    text: str,
    *,
    y0: float,
    y1: float,
    page_height: float,
) -> bool:
    normalized = _normalize_block_text(text)
    if not normalized:
        return False
    if any(pattern.search(normalized) for pattern in PAGE_BOTTOM_NOISE_PATTERNS):
        return True
    if (page_height - y1) > 28.0 and (page_height - y0) > 40.0:
        return False
    return False


def filter_page_noise_blocks(
    text_blocks: list[tuple[float, float, float, float, str]],
    *,
    page_height: float,
) -> list[tuple[float, float, float, float, str]]:
    filtered: list[tuple[float, float, float, float, str]] = []
    for x0, y0, x1, y1, text in text_blocks:
        normalized = (text or "").strip()
        if not normalized:
            continue
        if _is_top_page_noise_block(normalized, y0=y0, y1=y1):
            continue
        if _is_bottom_page_noise_block(normalized, y0=y0, y1=y1, page_height=page_height):
            continue
        filtered.append((x0, y0, x1, y1, normalized))
    return filtered


def collect_text_blocks_with_text_for_clip(
    page,
    *,
    clip_x0: float,
    clip_x1: float,
    raw_y0: float,
    raw_y1: float,
) -> list[tuple[float, float, float, float, str]]:
    blocks: list[tuple[float, float, float, float, str]] = []
    for row in page.get_text("blocks", sort=True):
        if len(row) < 5:
            continue
        x0, y0, x1, y1, text = row[0], row[1], row[2], row[3], row[4]
        x0 = float(x0)
        y0 = float(y0)
        x1 = float(x1)
        y1 = float(y1)
        if x1 <= x0 or y1 <= y0:
            continue

        x_overlap = min(x1, clip_x1) - max(x0, clip_x0)
        y_overlap = min(y1, raw_y1) - max(y0, raw_y0)
        if x_overlap <= 0 or y_overlap <= 0:
            continue
        if x_overlap / (x1 - x0) < 0.3:
            continue

        normalized = str(text or "").strip()
        if not normalized:
            continue
        blocks.append((x0, y0, x1, y1, normalized))
    return blocks


def _join_text_from_blocks(text_blocks: list[tuple[float, float, float, float, str]]) -> str:
    return "\n".join(text.strip() for *_coords, text in text_blocks if text.strip()).strip()


def split_segment_text_for_state(
    module5,
    *,
    clip_text: str,
    choices_started: bool,
) -> tuple[str, str, bool]:
    normalized = (clip_text or "").strip()
    if not normalized:
        return "", "", choices_started
    if choices_started:
        return "", normalized, True

    split_fn = getattr(module5, "split_question_and_choices", None)
    if split_fn is None:
        return normalized, "", False

    question_text, choices_text = split_fn(normalized)
    question_text = question_text.strip()
    choices_text = choices_text.strip()
    return question_text, choices_text, bool(choices_text)


def _split_problem_and_choices_clip_by_choice_blocks_fallback(
    *,
    clip_y0: float,
    clip_y1: float,
    text_blocks: list[tuple[float, float, float, float, str]],
) -> tuple[tuple[float, float] | None, tuple[float, float] | None]:
    choice_starts: list[float] = []
    for _x0, block_y0, _x1, _y1, block_text in text_blocks:
        for line in block_text.splitlines():
            if OCR_CHOICE_LINE_RE.match(line):
                choice_starts.append(max(clip_y0, block_y0))
                break

    if not choice_starts:
        return (clip_y0, clip_y1), None

    split_y = min(choice_starts)
    problem_end = min(clip_y1, split_y - 1.0)
    choices_start = max(clip_y0, split_y)
    problem_clip = (clip_y0, problem_end) if problem_end > clip_y0 + 4.0 else None
    choices_clip = (choices_start, clip_y1) if clip_y1 > choices_start + 4.0 else None
    if problem_clip is None and choices_clip is None:
        return (clip_y0, clip_y1), None
    return problem_clip, choices_clip


def resolve_segment_clips_for_state(
    *,
    clip_y0: float,
    clip_y1: float,
    text_blocks: list[tuple[float, float, float, float, str]],
    choices_started: bool,
    split_clip_fn=None,
) -> tuple[tuple[float, float] | None, tuple[float, float] | None, bool]:
    if not text_blocks:
        return None, None, choices_started
    if choices_started:
        return None, (clip_y0, clip_y1), True

    if split_clip_fn is None:
        problem_clip, choices_clip = _split_problem_and_choices_clip_by_choice_blocks_fallback(
            clip_y0=clip_y0,
            clip_y1=clip_y1,
            text_blocks=text_blocks,
        )
    else:
        problem_clip, choices_clip = split_clip_fn(
            clip_y0=clip_y0,
            clip_y1=clip_y1,
            text_blocks=[(y0, y1, text) for _x0, y0, _x1, y1, text in text_blocks],
        )
    return problem_clip, choices_clip, choices_started or (choices_clip is not None)


def load_module_5():
    module_name = "extract_latex_split_images_module"
    module_path = REPO_ROOT / "5_extract_all_text_and_save_latex_split_images.py"

    spec = importlib.util.spec_from_file_location(module_name, str(module_path))
    if spec is None or spec.loader is None:
        raise RuntimeError("5번 모듈을 로드할 수 없습니다.")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def apply_render_safety_patches(module5) -> None:
    original_refine_x = module5.refine_clip_x_to_text_blocks

    def safer_refine_clip_x_to_text_blocks(raw_x0, raw_x1, text_block_boxes):
        refined_x0, refined_x1 = original_refine_x(raw_x0, raw_x1, text_block_boxes)

        # bbox 미세 오차로 우측 글자가 잘리는 케이스를 방지한다.
        if (raw_x1 - refined_x1) <= 24.0:
            refined_x1 = raw_x1
        if (refined_x0 - raw_x0) <= 8.0:
            refined_x0 = raw_x0

        if refined_x1 <= refined_x0 + 4.0:
            return raw_x0, raw_x1
        return refined_x0, refined_x1

    module5.refine_clip_x_to_text_blocks = safer_refine_clip_x_to_text_blocks

    if hasattr(module5, "expand_column_bounds"):
        original_expand = module5.expand_column_bounds

        def safer_expand_column_bounds(
            columns,
            column_index,
            page_width,
            margin=18.0,
            gap_guard=2.0,
        ):
            x0, x1 = original_expand(
                columns,
                column_index,
                page_width,
                max(float(margin), 72.0),
                min(float(gap_guard), 0.5),
            )
            return widen_left_column_if_tight_gap(columns, column_index, page_width, x0, x1)

        module5.expand_column_bounds = safer_expand_column_bounds

    if hasattr(module5, "detect_page_columns"):
        original_detect_page_columns = module5.detect_page_columns

        def safer_detect_page_columns(doc):
            page_columns = original_detect_page_columns(doc)
            for page_idx, page in enumerate(doc):
                columns = page_columns[page_idx]
                starts = collect_question_start_x_centers(page, module5)
                page_width = float(page.rect.width)
                separator_x = detect_vertical_separator_x_in_page(page)
                if separator_x is not None:
                    page_columns[page_idx] = build_two_columns_from_separator(
                        page_width=page_width,
                        separator_x=separator_x,
                    )
                    continue
                page_columns[page_idx] = rebuild_unbalanced_two_columns_from_question_starts(
                    columns=page_columns[page_idx],
                    page_width=page_width,
                    question_start_x_centers=starts,
                )
                columns = page_columns[page_idx]
                if should_collapse_tight_two_columns(columns, page_width, starts):
                    page_columns[page_idx] = [(0.0, page_width)]
            return page_columns

        module5.detect_page_columns = safer_detect_page_columns


def should_collapse_tight_two_columns(
    columns: List[tuple[float, float]],
    page_width: float,
    question_start_x_centers: List[float],
) -> bool:
    if len(columns) != 2 or page_width <= 0 or not question_start_x_centers:
        return False

    left, right = sorted(columns, key=lambda c: c[0])
    gap = right[0] - left[1]
    covered = (left[1] - left[0]) + (right[1] - right[0]) + max(gap, 0.0)
    if not (gap <= 12.0 and (covered / page_width) >= 0.85):
        return False

    split_x = (left[1] + right[0]) / 2.0
    right_starts = [x for x in question_start_x_centers if x > split_x]
    return len(right_starts) == 0


def collect_question_start_x_centers(page, module5) -> List[float]:
    centers: List[float] = []
    text_dict = page.get_text("dict", sort=True)
    for block in text_dict.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            line_text = "".join(span.get("text", "") for span in spans).strip()
            if not line_text or not module5.QUESTION_START_RE.match(line_text):
                continue

            if spans:
                x0 = float(spans[0].get("bbox", [0, 0, 0, 0])[0])
                x1 = float(spans[-1].get("bbox", [0, 0, 0, 0])[2])
            else:
                x0, _, x1, _ = line.get("bbox", [0, 0, 0, 0])
                x0 = float(x0)
                x1 = float(x1)
            centers.append((x0 + x1) / 2.0)
    return centers


def widen_left_column_if_tight_gap(
    columns: List[tuple[float, float]],
    column_index: int,
    page_width: float,
    x0: float,
    x1: float,
) -> tuple[float, float]:
    if len(columns) != 2 or column_index != 0 or page_width <= 0:
        return x0, x1

    left, right = sorted(columns, key=lambda c: c[0])
    gap = right[0] - left[1]
    if gap > 12.0:
        return x0, x1

    # 타이트한 2단 경계에서 우측 글자 획이 잘리는 문제를 막기 위해
    # 좌측 컬럼의 우측 경계를 제한적으로 오른쪽으로 확장한다.
    max_overlap = 24.0
    widened_x1 = min(page_width, x1 + max_overlap)
    return x0, widened_x1


def build_two_columns_from_separator(
    page_width: float,
    separator_x: float,
    separator_half_gap: float = 8.0,
) -> list[tuple[float, float]]:
    if page_width <= 0:
        return [(0.0, page_width)]
    left_x1 = max(0.0, min(page_width, separator_x - separator_half_gap))
    right_x0 = max(0.0, min(page_width, separator_x + separator_half_gap))
    if right_x0 <= left_x1 + 4.0:
        return [(0.0, page_width)]
    return [(0.0, left_x1), (right_x0, page_width)]


def rebuild_unbalanced_two_columns_from_question_starts(
    columns: List[tuple[float, float]],
    page_width: float,
    question_start_x_centers: List[float],
) -> List[tuple[float, float]]:
    if len(columns) != 2 or page_width <= 0 or len(question_start_x_centers) < 2:
        return columns

    left, right = sorted(columns, key=lambda c: c[0])
    left_width = max(0.0, left[1] - left[0])
    right_width = max(0.0, right[1] - right[0])
    if min(left_width, right_width) / page_width >= 0.3:
        return [left, right]

    starts = sorted(float(x) for x in question_start_x_centers)
    max_gap = 0.0
    split_x = None
    for i in range(len(starts) - 1):
        gap = starts[i + 1] - starts[i]
        if gap > max_gap:
            max_gap = gap
            split_x = (starts[i] + starts[i + 1]) / 2.0

    if split_x is None or max_gap < page_width * 0.18:
        return [left, right]
    if not (page_width * 0.25 <= split_x <= page_width * 0.75):
        return [left, right]

    repaired = build_two_columns_from_separator(
        page_width=page_width,
        separator_x=split_x,
        separator_half_gap=4.0,
    )
    return repaired if len(repaired) == 2 else [left, right]


def infer_vertical_separator_x(
    image_width: int,
    col_stats_fn,
    *,
    search_left_ratio: float = 0.4,
    search_right_ratio: float = 0.6,
) -> float | None:
    if image_width < 120:
        return None
    x0 = max(1, int(image_width * search_left_ratio))
    x1 = min(image_width - 2, int(image_width * search_right_ratio))
    if x1 <= x0:
        return None

    candidates: list[int] = []
    for x in range(x0, x1 + 1):
        mean, stddev, dark_ratio, longest_dark_run_ratio = col_stats_fn(x)
        if _looks_like_vertical_boundary_rule(
            mean=mean,
            stddev=stddev,
            dark_ratio=dark_ratio,
            longest_dark_run_ratio=longest_dark_run_ratio,
        ):
            candidates.append(x)

    if not candidates:
        return None

    best_start = candidates[0]
    best_end = candidates[0]
    cur_start = candidates[0]
    cur_end = candidates[0]
    for x in candidates[1:]:
        if x == cur_end + 1:
            cur_end = x
            continue
        if (cur_end - cur_start) > (best_end - best_start):
            best_start, best_end = cur_start, cur_end
        cur_start = x
        cur_end = x
    if (cur_end - cur_start) > (best_end - best_start):
        best_start, best_end = cur_start, cur_end

    return (best_start + best_end) / 2.0


def detect_vertical_separator_x_in_page(page) -> float | None:
    try:
        import fitz
    except Exception:
        return None
    try:
        pix = page.get_pixmap(matrix=fitz.Matrix(1, 1), alpha=False)
    except Exception:
        return None
    return infer_vertical_separator_x(
        image_width=int(pix.width),
        col_stats_fn=lambda x: _col_stats_from_pixmap(pix, x),
    )


def select_pdf_files_with_gui() -> List[str]:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception:
        return select_pdf_files_with_osascript()

    root = tk.Tk()
    root.withdraw()
    root.update()
    selected = filedialog.askopenfilenames(
        title="PDF 파일 선택 (여러 개 가능)",
        filetypes=[("PDF files", "*.pdf")],
    )
    root.destroy()

    return [str(Path(p)) for p in selected]


def _parse_osascript_output(stdout: str) -> List[str]:
    return [line.strip() for line in stdout.splitlines() if line.strip()]


def select_pdf_files_with_osascript() -> List[str]:
    if sys.platform != "darwin":
        raise RuntimeError("GUI 선택창을 사용할 수 없습니다. --pdf 옵션으로 파일을 지정하세요.")

    script_lines = [
        'set chosenFiles to choose file with prompt "PDF 파일 선택 (여러 개 가능)" of type {"pdf"} with multiple selections allowed',
        "set outputText to \"\"",
        "repeat with f in chosenFiles",
        "set outputText to outputText & POSIX path of f & linefeed",
        "end repeat",
        "return outputText",
    ]
    cmd = ["osascript"]
    for line in script_lines:
        cmd.extend(["-e", line])

    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    stderr = (proc.stderr or "").strip().lower()

    if proc.returncode != 0:
        # 사용자가 취소한 경우 빈 목록으로 처리
        if "user canceled" in stderr or "cancelled" in stderr:
            return []
        raise RuntimeError(
            "GUI 파일 선택에 실패했습니다. --pdf 옵션으로 파일을 지정해 주세요."
        )

    return _parse_osascript_output(proc.stdout)


def dedupe_dir_name(base_root: Path, desired_name: str) -> Path:
    candidate = base_root / desired_name
    if not candidate.exists():
        return candidate

    index = 2
    while True:
        next_candidate = base_root / f"{desired_name}_{index}"
        if not next_candidate.exists():
            return next_candidate
        index += 1


def prepare_output_paths(pdf_path: str, output_root: Path) -> tuple[Path, Path, Path, Path]:
    pdf_name = Path(pdf_path).stem
    target_dir = dedupe_dir_name(output_root, pdf_name)
    image_dir = target_dir / "latex_pages"
    text_dir = target_dir / "question_texts"
    out_tex = target_dir / "output.tex"
    return target_dir, image_dir, text_dir, out_tex


def _looks_like_boundary_rule(
    mean: float,
    stddev: float,
    dark_ratio: float,
    longest_dark_run_ratio: float,
) -> bool:
    if dark_ratio >= 0.88:
        return True
    if stddev <= 8.0 and mean <= 247.0:
        return True
    if (
        longest_dark_run_ratio >= 0.75
        and dark_ratio >= 0.18
        and mean <= 252.0
        and stddev <= 32.0
    ):
        return True
    return False


def _looks_like_vertical_boundary_rule(
    mean: float,
    stddev: float,
    dark_ratio: float,
    longest_dark_run_ratio: float,
) -> bool:
    if longest_dark_run_ratio >= 0.9 and dark_ratio >= 0.65:
        return True
    if longest_dark_run_ratio >= 0.92 and stddev <= 12.0 and mean <= 250.0:
        return True
    if longest_dark_run_ratio >= 0.85 and dark_ratio >= 0.75 and stddev <= 45.0 and mean <= 230.0:
        return True
    return False


def _row_stats(gray_image, y: int) -> tuple[float, float, float, float]:
    width, _ = gray_image.size
    pixels = gray_image.load()
    total = 0.0
    total_sq = 0.0
    dark_count = 0
    longest_run = 0
    current_run = 0
    for x in range(width):
        value = float(pixels[x, y])
        total += value
        total_sq += value * value
        if value <= 235.0:
            dark_count += 1
            current_run += 1
            if current_run > longest_run:
                longest_run = current_run
        else:
            current_run = 0

    mean = total / width
    variance = max(0.0, (total_sq / width) - (mean * mean))
    stddev = variance ** 0.5
    dark_ratio = dark_count / width
    longest_dark_run_ratio = longest_run / width
    return mean, stddev, dark_ratio, longest_dark_run_ratio


def _col_stats(gray_image, x: int) -> tuple[float, float, float, float]:
    _, height = gray_image.size
    pixels = gray_image.load()
    total = 0.0
    total_sq = 0.0
    dark_count = 0
    longest_run = 0
    current_run = 0
    for y in range(height):
        value = float(pixels[x, y])
        total += value
        total_sq += value * value
        if value <= 235.0:
            dark_count += 1
            current_run += 1
            if current_run > longest_run:
                longest_run = current_run
        else:
            current_run = 0

    mean = total / height
    variance = max(0.0, (total_sq / height) - (mean * mean))
    stddev = variance ** 0.5
    dark_ratio = dark_count / height
    longest_dark_run_ratio = longest_run / height
    return mean, stddev, dark_ratio, longest_dark_run_ratio


def _row_stats_from_pixmap(pixmap, y: int) -> tuple[float, float, float, float]:
    width = int(pixmap.width)
    channels = int(pixmap.n)
    samples = pixmap.samples
    row_start = y * width * channels

    total = 0.0
    total_sq = 0.0
    dark_count = 0
    longest_run = 0
    current_run = 0
    for x in range(width):
        i = row_start + (x * channels)
        if channels >= 3:
            r = samples[i]
            g = samples[i + 1]
            b = samples[i + 2]
            value = (0.299 * r) + (0.587 * g) + (0.114 * b)
        else:
            value = float(samples[i])

        total += value
        total_sq += value * value
        if value <= 235.0:
            dark_count += 1
            current_run += 1
            if current_run > longest_run:
                longest_run = current_run
        else:
            current_run = 0

    mean = total / width
    variance = max(0.0, (total_sq / width) - (mean * mean))
    stddev = variance ** 0.5
    dark_ratio = dark_count / width
    longest_dark_run_ratio = longest_run / width
    return mean, stddev, dark_ratio, longest_dark_run_ratio


def _col_stats_from_pixmap(pixmap, x: int) -> tuple[float, float, float, float]:
    height = int(pixmap.height)
    width = int(pixmap.width)
    channels = int(pixmap.n)
    samples = pixmap.samples

    total = 0.0
    total_sq = 0.0
    dark_count = 0
    longest_run = 0
    current_run = 0
    for y in range(height):
        i = ((y * width) + x) * channels
        if channels >= 3:
            r = samples[i]
            g = samples[i + 1]
            b = samples[i + 2]
            value = (0.299 * r) + (0.587 * g) + (0.114 * b)
        else:
            value = float(samples[i])

        total += value
        total_sq += value * value
        if value <= 235.0:
            dark_count += 1
            current_run += 1
            if current_run > longest_run:
                longest_run = current_run
        else:
            current_run = 0

    mean = total / height
    variance = max(0.0, (total_sq / height) - (mean * mean))
    stddev = variance ** 0.5
    dark_ratio = dark_count / height
    longest_dark_run_ratio = longest_run / height
    return mean, stddev, dark_ratio, longest_dark_run_ratio


def _find_side_trim_by_column_stats(
    image_width: int,
    *,
    from_left: bool,
    max_trim_px: int,
    edge_scan_cols: int,
    col_stats_fn,
) -> int:
    scan_count = min(edge_scan_cols, image_width)
    for offset in range(scan_count):
        x = offset if from_left else (image_width - 1 - offset)
        mean, stddev, dark_ratio, longest_dark_run_ratio = col_stats_fn(x)
        if _looks_like_vertical_boundary_rule(
            mean=mean,
            stddev=stddev,
            dark_ratio=dark_ratio,
            longest_dark_run_ratio=longest_dark_run_ratio,
        ):
            trim = offset + 1
            return min(trim, max_trim_px)
    return 0


def _count_boundary_rows_to_trim(
    gray_image,
    *,
    from_top: bool,
    max_trim_px: int,
    edge_scan_rows: int,
) -> int:
    _, height = gray_image.size
    scan_count = min(edge_scan_rows, height)
    trimmed = 0

    for offset in range(scan_count):
        y = offset if from_top else (height - 1 - offset)
        mean, stddev, dark_ratio, longest_dark_run_ratio = _row_stats(gray_image, y)
        looks_like_rule = _looks_like_boundary_rule(
            mean=mean,
            stddev=stddev,
            dark_ratio=dark_ratio,
            longest_dark_run_ratio=longest_dark_run_ratio,
        )
        if not looks_like_rule:
            break
        trimmed += 1
        if trimmed >= max_trim_px:
            break

    return trimmed


def _count_boundary_rows_to_trim_with_row_stats(
    image_height: int,
    *,
    from_top: bool,
    max_trim_px: int,
    edge_scan_rows: int,
    row_stats_fn,
) -> int:
    scan_count = min(edge_scan_rows, image_height)
    trimmed = 0

    for offset in range(scan_count):
        y = offset if from_top else (image_height - 1 - offset)
        mean, stddev, dark_ratio, longest_dark_run_ratio = row_stats_fn(y)
        looks_like_rule = _looks_like_boundary_rule(
            mean=mean,
            stddev=stddev,
            dark_ratio=dark_ratio,
            longest_dark_run_ratio=longest_dark_run_ratio,
        )
        if not looks_like_rule:
            break
        trimmed += 1
        if trimmed >= max_trim_px:
            break

    return trimmed


def _refine_image_page_boundaries_with_fitz(
    image_path: str | Path,
    *,
    max_trim_px: int = 8,
    edge_scan_rows: int = 12,
    max_side_trim_px: int = 48,
    edge_scan_cols: int = 56,
) -> bool:
    try:
        import fitz
    except Exception:
        return False

    path = Path(image_path)
    if not path.exists():
        return False

    with fitz.open(str(path)) as image_doc:
        if len(image_doc) == 0:
            return False
        page = image_doc[0]
        try:
            pix = fitz.Pixmap(str(path))
        except Exception:
            pix = page.get_pixmap(alpha=False)
        if pix.width <= 4 or pix.height <= 4:
            return False

        top_trim = _count_boundary_rows_to_trim_with_row_stats(
            pix.height,
            from_top=True,
            max_trim_px=max_trim_px,
            edge_scan_rows=edge_scan_rows,
            row_stats_fn=lambda y: _row_stats_from_pixmap(pix, y),
        )
        bottom_trim = _count_boundary_rows_to_trim_with_row_stats(
            pix.height,
            from_top=False,
            max_trim_px=max_trim_px,
            edge_scan_rows=edge_scan_rows,
            row_stats_fn=lambda y: _row_stats_from_pixmap(pix, y),
        )

        left_trim = _find_side_trim_by_column_stats(
            int(pix.width),
            from_left=True,
            max_trim_px=max_side_trim_px,
            edge_scan_cols=edge_scan_cols,
            col_stats_fn=lambda x: _col_stats_from_pixmap(pix, x),
        )
        right_trim = _find_side_trim_by_column_stats(
            int(pix.width),
            from_left=False,
            max_trim_px=max_side_trim_px,
            edge_scan_cols=edge_scan_cols,
            col_stats_fn=lambda x: _col_stats_from_pixmap(pix, x),
        )

        if (top_trim + bottom_trim + left_trim + right_trim) == 0:
            return False
        if (pix.height - (top_trim + bottom_trim)) < 10:
            return False
        if (pix.width - (left_trim + right_trim)) < 20:
            return False

        page_height = float(page.rect.height)
        page_width = float(page.rect.width)
        if page_width <= 0.0 or page_height <= 0.0:
            return False
        top_ratio = top_trim / float(pix.height)
        bottom_ratio = bottom_trim / float(pix.height)
        left_ratio = left_trim / float(pix.width)
        right_ratio = right_trim / float(pix.width)

        clip_left = max(0.0, page_width * left_ratio)
        clip_top = max(0.0, page_height * top_ratio)
        clip_right = min(page_width, page_width * (1.0 - right_ratio))
        clip_bottom = min(page_height, page_height * (1.0 - bottom_ratio))
        if (clip_bottom - clip_top) <= 1.0 or (clip_right - clip_left) <= 1.0:
            return False

        clip_rect = fitz.Rect(clip_left, clip_top, clip_right, clip_bottom)
        matrix = fitz.Matrix(pix.width / page_width, pix.height / page_height)
        cropped = page.get_pixmap(clip=clip_rect, matrix=matrix, alpha=False)
        cropped.save(str(path))
        return True


def refine_image_page_boundaries(
    image_path: str | Path,
    *,
    max_trim_px: int = 8,
    edge_scan_rows: int = 12,
    max_side_trim_px: int = 48,
    edge_scan_cols: int = 56,
) -> bool:
    global _PIL_IMAGE_AVAILABLE
    path = Path(image_path)
    if not path.exists():
        return False

    try:
        from PIL import Image
        _PIL_IMAGE_AVAILABLE = True
    except Exception:
        _PIL_IMAGE_AVAILABLE = False
        return _refine_image_page_boundaries_with_fitz(
            path,
            max_trim_px=max_trim_px,
            edge_scan_rows=edge_scan_rows,
            max_side_trim_px=max_side_trim_px,
            edge_scan_cols=edge_scan_cols,
        )

    with Image.open(path) as img:
        if img.height <= 4 or img.width <= 4:
            return False

        gray = img.convert("L")
        top_trim = _count_boundary_rows_to_trim(
            gray,
            from_top=True,
            max_trim_px=max_trim_px,
            edge_scan_rows=edge_scan_rows,
        )
        bottom_trim = _count_boundary_rows_to_trim(
            gray,
            from_top=False,
            max_trim_px=max_trim_px,
            edge_scan_rows=edge_scan_rows,
        )

        left_trim = _find_side_trim_by_column_stats(
            img.width,
            from_left=True,
            max_trim_px=max_side_trim_px,
            edge_scan_cols=edge_scan_cols,
            col_stats_fn=lambda x: _col_stats(gray, x),
        )
        right_trim = _find_side_trim_by_column_stats(
            img.width,
            from_left=False,
            max_trim_px=max_side_trim_px,
            edge_scan_cols=edge_scan_cols,
            col_stats_fn=lambda x: _col_stats(gray, x),
        )

        if (top_trim + bottom_trim + left_trim + right_trim) == 0:
            return False
        if (img.height - (top_trim + bottom_trim)) < 10:
            return False
        if (img.width - (left_trim + right_trim)) < 20:
            return False

        cropped = img.crop(
            (
                left_trim,
                top_trim,
                img.width - right_trim,
                img.height - bottom_trim,
            )
        )
        cropped.save(path)
        return True


def refine_rendered_image_paths(image_paths: Iterable[str | Path]) -> int:
    refined = 0
    seen: set[str] = set()
    for image_path in image_paths:
        path_text = str(Path(image_path))
        if path_text in seen:
            continue
        seen.add(path_text)
        if refine_image_page_boundaries(path_text):
            refined += 1
    return refined


def is_image_refine_available() -> bool:
    global _PIL_IMAGE_AVAILABLE
    if _PIL_IMAGE_AVAILABLE is True:
        return True

    if _PIL_IMAGE_AVAILABLE is None:
        try:
            from PIL import Image  # noqa: F401
            _PIL_IMAGE_AVAILABLE = True
            return True
        except Exception:
            _PIL_IMAGE_AVAILABLE = False

    try:
        import fitz  # noqa: F401
        return True
    except Exception:
        return False


def collect_output_image_paths(question_images, shared_passages: List[SharedPassageSet]) -> List[str]:
    paths: List[str] = []
    for item in question_images:
        paths.extend(item.problem_image_paths)
        paths.extend(item.choices_image_paths)
    for shared in shared_passages:
        paths.extend(shared.image_paths)
    return paths


def clone_question_images(module5, question_images):
    return [
        module5.QuestionImageSet(
            index=item.index,
            qno=item.qno,
            problem_image_paths=list(item.problem_image_paths),
            choices_image_paths=list(item.choices_image_paths),
        )
        for item in question_images
    ]


def clone_question_texts(module5, question_texts):
    return [
        module5.QuestionTextSet(
            index=item.index,
            qno=item.qno,
            question_text=item.question_text,
            choices_text=item.choices_text,
        )
        for item in question_texts
    ]


def _build_combined_text(question_text: str, choices_text: str) -> str:
    if question_text and choices_text:
        return f"{question_text}\n{choices_text}"
    if question_text:
        return question_text
    return choices_text


def _split_pre_shared_text(module5, pre_shared_text: str) -> tuple[str, str]:
    split_fn = getattr(module5, "split_question_and_choices", None)
    if split_fn is None:
        return pre_shared_text.strip(), ""
    question_text, choices_text = split_fn(pre_shared_text.strip())
    return question_text.strip(), choices_text.strip()


def _extract_shared_image(
    source_image_item,
    image_dir: Path,
    passage_id: str,
) -> List[str]:
    if source_image_item is None:
        return []

    candidate_path: str | None = None
    if len(source_image_item.problem_image_paths) >= 2:
        candidate_path = source_image_item.problem_image_paths[-1]
        source_image_item.problem_image_paths = source_image_item.problem_image_paths[:-1]
    elif source_image_item.choices_image_paths:
        candidate_path = source_image_item.choices_image_paths[-1]
        source_image_item.choices_image_paths = source_image_item.choices_image_paths[:-1]

    if not candidate_path:
        return []

    source_path = Path(candidate_path)
    if not source_path.exists():
        return []

    dest_path = image_dir / f"{passage_id}_part_01.png"
    shutil.copyfile(source_path, dest_path)
    return [str(dest_path)]


def extract_shared_passages(module5, question_images, question_texts, image_dir: Path):
    question_images_out = clone_question_images(module5, question_images)
    question_texts_out = clone_question_texts(module5, question_texts)

    image_by_index = {item.index: item for item in question_images_out}
    qno_set = {item.qno for item in question_texts_out if item.qno is not None}
    shared_passages: List[SharedPassageSet] = []
    shared_map: dict[int, str] = {}

    for text_item in question_texts_out:
        combined_text = _build_combined_text(text_item.question_text, text_item.choices_text).strip()
        if not combined_text:
            continue

        match = SHARED_PASSAGE_RE.search(combined_text)
        if match is None:
            continue

        start_qno = int(match.group(1))
        end_qno = int(match.group(2))
        if start_qno > end_qno:
            start_qno, end_qno = end_qno, start_qno

        target_qnos = [qno for qno in range(start_qno, end_qno + 1) if qno in qno_set]
        if not target_qnos:
            continue

        passage_id = f"shared_passage_{start_qno:03d}_{end_qno:03d}"
        if any(item.passage_id == passage_id for item in shared_passages):
            continue

        pre_shared_text = combined_text[:match.start()].strip()
        shared_text = combined_text[match.start():].strip()
        if not shared_text:
            continue

        # 공통 지문 이전 텍스트를 다시 problem/choices로 분해해 원 문항에 반영한다.
        question_text, choices_text = _split_pre_shared_text(module5, pre_shared_text)
        text_item.question_text = question_text
        text_item.choices_text = choices_text

        source_image_item = image_by_index.get(text_item.index)
        shared_image_paths = _extract_shared_image(
            source_image_item=source_image_item,
            image_dir=image_dir,
            passage_id=passage_id,
        )

        shared_passages.append(
            SharedPassageSet(
                passage_id=passage_id,
                start_qno=start_qno,
                end_qno=end_qno,
                text=shared_text,
                image_paths=shared_image_paths,
            )
        )
        for qno in target_qnos:
            shared_map[qno] = passage_id

    return question_images_out, question_texts_out, shared_passages, shared_map


def relativize_question_images(module5, question_images, out_tex: Path):
    question_images_for_tex = []
    for item in question_images:
        problem_rel_paths = [
            os.path.relpath(path, start=out_tex.parent) for path in item.problem_image_paths
        ]
        choices_rel_paths = [
            os.path.relpath(path, start=out_tex.parent) for path in item.choices_image_paths
        ]
        question_images_for_tex.append(
            module5.QuestionImageSet(
                index=item.index,
                qno=item.qno,
                problem_image_paths=problem_rel_paths,
                choices_image_paths=choices_rel_paths,
            )
        )
    return question_images_for_tex


def relativize_shared_passages(
    shared_passages: List[SharedPassageSet],
    out_tex: Path,
) -> List[SharedPassageSet]:
    out: List[SharedPassageSet] = []
    for item in shared_passages:
        out.append(
            SharedPassageSet(
                passage_id=item.passage_id,
                start_qno=item.start_qno,
                end_qno=item.end_qno,
                text=item.text,
                image_paths=[os.path.relpath(path, start=out_tex.parent) for path in item.image_paths],
            )
        )
    return out


def build_shared_passage_tex_block(item: SharedPassageSet, mapped_qnos: List[int]) -> List[str]:
    qno_text = ",".join(f"q{qno}" for qno in mapped_qnos)
    lines: List[str] = [
        rf"% {qno_text} -> {item.passage_id}.txt",
        rf"\subsection*{{Shared Passage (No. {item.start_qno}-{item.end_qno})}}",
    ]

    if not item.image_paths:
        lines.append(r"% shared passage image unavailable")
        lines.append("")
        return lines

    for rel_path in item.image_paths:
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
    return lines


def _question_section_title_line(item) -> str:
    if item.qno is None:
        return rf"\section*{{Question {item.index}}}"
    return rf"\section*{{Question {item.index} (No. {item.qno})}}"


def build_latex_document(
    module5,
    pdf_name: str,
    question_images,
    shared_passages: List[SharedPassageSet],
    shared_map: dict[int, str],
) -> str:
    base_tex = module5.build_latex_document(pdf_name=pdf_name, question_images=question_images)
    if not shared_passages:
        return base_tex

    shared_by_id = {item.passage_id: item for item in shared_passages}
    qnos_by_passage: dict[str, List[int]] = {}
    for qno, passage_id in shared_map.items():
        qnos_by_passage.setdefault(passage_id, []).append(qno)

    anchor_by_section_line: dict[str, List[str]] = {}
    anchored_passage_ids: set[str] = set()
    for q_item in question_images:
        if q_item.qno is None:
            continue
        passage_id = shared_map.get(q_item.qno)
        if passage_id is None or passage_id in anchored_passage_ids:
            continue
        line = _question_section_title_line(q_item)
        anchor_by_section_line.setdefault(line, []).append(passage_id)
        anchored_passage_ids.add(passage_id)

    inserted: set[str] = set()
    out_lines: List[str] = []
    for line in base_tex.splitlines():
        if line in anchor_by_section_line:
            for passage_id in anchor_by_section_line[line]:
                passage = shared_by_id.get(passage_id)
                if passage is None or passage_id in inserted:
                    continue
                out_lines.extend(
                    build_shared_passage_tex_block(
                        item=passage,
                        mapped_qnos=sorted(qnos_by_passage.get(passage_id, [])),
                    )
                )
                inserted.add(passage_id)

        if line == r"\end{document}":
            # 대응 문항을 찾지 못한 shared_passage는 문서 끝에 추가한다.
            for passage in shared_passages:
                if passage.passage_id in inserted:
                    continue
                out_lines.extend(
                    build_shared_passage_tex_block(
                        item=passage,
                        mapped_qnos=sorted(qnos_by_passage.get(passage.passage_id, [])),
                    )
                )
                inserted.add(passage.passage_id)

        out_lines.append(line)

    return "\n".join(out_lines) + "\n"


def save_split_texts(
    module5,
    out_dir: Path,
    question_texts,
    shared_passages: List[SharedPassageSet],
    shared_map: dict[int, str],
) -> None:
    module5.save_split_texts(out_dir, question_texts)
    if not shared_passages:
        return

    for item in shared_passages:
        passage_text_path = out_dir / f"{item.passage_id}.txt"
        passage_text_path.write_text(item.text, encoding="utf-8")

    payload = {
        str(qno): {"shared_passage": f"{passage_id}.txt"}
        for qno, passage_id in sorted(shared_map.items())
    }
    mapping_path = out_dir / "question_passage_map.json"
    mapping_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def should_use_ocr_fallback(text: str, min_chars: int = 30) -> bool:
    _ = min_chars  # 하위 호환을 위해 시그니처는 유지한다.
    return normalize_text_for_hash(text) == ""


def _warn_ocr_once(key: str, message: str) -> None:
    if key in _OCR_WARNED_KEYS:
        return
    _OCR_WARNED_KEYS.add(key)
    print(message, file=sys.stderr)


def _preprocess_image_for_ocr(image):
    # 스캔본에서 명암 대비를 단순화해 OCR 인식률을 높인다.
    gray = image.convert("L")
    return gray.point(lambda v: 0 if v < 180 else 255)


def detect_vertical_separator_x_in_image(image) -> float | None:
    try:
        gray = image.convert("L")
        return infer_vertical_separator_x(
            image_width=int(gray.size[0]),
            col_stats_fn=lambda x: _col_stats(gray, x),
        )
    except Exception:
        return None


def _ocr_from_single_image(pytesseract, image, ocr_lang: str) -> str:
    separator_x = detect_vertical_separator_x_in_image(image)
    if separator_x is not None:
        width, height = image.size
        gap = max(8, int(width * 0.015))
        left = image.crop((0, 0, max(1, int(separator_x) - gap), height))
        right = image.crop((min(width - 1, int(separator_x) + gap), 0, width, height))
        left_text = _ocr_from_single_region(pytesseract, left, ocr_lang=ocr_lang)
        right_text = _ocr_from_single_region(pytesseract, right, ocr_lang=ocr_lang)
        combined = "\n".join(part for part in [left_text, right_text] if normalize_text_for_hash(part))
        if normalize_text_for_hash(combined):
            return combined.strip()

    return _ocr_from_single_region(pytesseract, image, ocr_lang=ocr_lang)


def _ocr_from_single_region(pytesseract, image, ocr_lang: str) -> str:
    candidates: list[str] = []
    for variant in _build_ocr_image_variants(image):
        for config in ("--oem 1 --psm 6", "--oem 1 --psm 4", "--oem 1 --psm 11"):
            text = pytesseract.image_to_string(variant, lang=ocr_lang, config=config)
            if normalize_text_for_hash(text):
                candidates.append(text.strip())
                if config != "--oem 1 --psm 11":
                    break

    return _select_best_ocr_candidate(candidates)


def _build_ocr_image_variants(image):
    variants = [_preprocess_image_for_ocr(image)]
    width, height = image.size
    if width < 1000:
        return variants

    split_x = int(width * 0.5)
    overlap = int(width * 0.08)
    left = image.crop((0, 0, min(width, split_x + overlap), height))
    right = image.crop((max(0, split_x - overlap), 0, width, height))
    variants.append(_preprocess_image_for_ocr(left))
    variants.append(_preprocess_image_for_ocr(right))
    return variants


def _select_best_ocr_candidate(candidates: list[str]) -> str:
    if not candidates:
        return ""
    return max(candidates, key=_score_ocr_candidate).strip()


def _score_ocr_candidate(text: str) -> tuple[int, int, int, int, int]:
    block = _extract_ocr_question_block(text, expected_qno=None)
    question_text, choices_text = _split_ocr_question_and_choices(block)
    first_qno = _parse_ocr_question_number(question_text)
    choice_count = sum(
        1
        for line in choices_text.splitlines()
        if OCR_CHOICE_LINE_RE.match(line) and not OCR_QUESTION_START_RE.match(line)
    )
    question_len = len(normalize_text_for_hash(question_text))
    block_len = len(normalize_text_for_hash(block))
    return (
        1 if first_qno is not None else 0,
        min(choice_count, 5),
        -(first_qno or 999),
        1 if question_len >= 20 else 0,
        -max(0, block_len - 1800),
    )


def _parse_ocr_question_number(question_text: str) -> int | None:
    if not question_text:
        return None
    first_line = question_text.splitlines()[0]
    return _parse_ocr_qno_from_line(first_line)


def _parse_ocr_qno_from_line(line: str) -> int | None:
    match = OCR_QUESTION_START_RE.match(line or "")
    if match is not None:
        try:
            return int(match.group(1))
        except ValueError:
            return None
    if OCR_QUESTION_START_SLASH7_RE.match(line or ""):
        return 7
    return None


def _is_ocr_question_start_line(line: str) -> bool:
    return _parse_ocr_qno_from_line(line) is not None


def _normalize_question_text_leading_number(question_text: str, qno: int | None) -> str:
    if qno is None or not question_text:
        return question_text
    lines = question_text.splitlines()
    if not lines:
        return question_text
    first = lines[0]
    normalized = re.sub(r"^\s*(?:/|\d{1,3})\s*[\.\)]\s*", f"{qno}. ", first)
    lines[0] = normalized
    return "\n".join(lines).strip()


def _normalize_common_ocr_phrases(text: str) -> str:
    if not text:
        return text
    out = text
    out = re.sub(r"Firmware\)O", "(Firmware)에", out)
    out = re.sub(r"관한\s*설명으로\s*22\s*것은\?", "관한 설명으로 옳은 것은?", out)
    out = re.sub(r"설명으로\s*올지\s*않은\s*것은\?", "설명으로 옳지 않은 것은?", out)
    out = re.sub(r"설명으로\s*율지\s*않은\s*것은\?", "설명으로 옳지 않은 것은?", out)
    out = re.sub(r"브리지\(\s*31006\s*\)", "브리지(Bridge)", out)
    out = re.sub(
        r"주로\s*하드디스크의\s*부트\s*레코드\s*부분에\s*AVEC\b",
        "주로 하드디스크의 부트 레코드 부분에 저장된다.",
        out,
    )
    out = re.sub(r"16%!\-=\(Hexadecimal\}", "16진수(Hexadecimal)", out)
    out = re.sub(r"A~FILAL\s*문지", "A~F의 문자", out)
    out = re.sub(r"10진수\s*실수0030로", "10진수 실수로", out)
    out = re.sub(r"\(\s*([1-5])\s+10진수\(0600130\s*정수", r"(\1) 10진수의 정수", out)
    out = re.sub(r"변환\s+하려면", "변환하려면", out)
    out = re.sub(r"변환\s*히\s*려면", "변환하려면", out)
    out = re.sub(r"더\s*이상\s*LA\s*지", "더 이상 나누어지", out)
    out = re.sub(r",\s*KE\s*제외한", ", 그 나머지를", out)
    out = re.sub(r"나머지를\s+나머지를", "나머지를", out)
    return out


def _has_choice_like_line(text: str) -> bool:
    for line in (text or "").splitlines():
        if OCR_CHOICE_LINE_RE.match(line) and not _is_ocr_question_start_line(line):
            return True
    return False


def _should_prefer_ocr_split(
    *,
    primary_question_text: str,
    primary_choices_text: str,
    ocr_question_text: str,
    ocr_choices_text: str,
) -> bool:
    if _has_choice_like_line(primary_question_text) and _has_choice_like_line(ocr_choices_text):
        return True
    if (not normalize_text_for_hash(primary_choices_text)) and normalize_text_for_hash(ocr_choices_text):
        return True
    return False


def _split_ocr_text_by_question_starts(text: str) -> list[tuple[int | None, str]]:
    lines = [line.rstrip() for line in (text or "").splitlines() if line.strip()]
    if not lines:
        return []

    starts: list[tuple[int, int | None]] = []
    for i, line in enumerate(lines):
        qno = _parse_ocr_qno_from_line(line)
        if qno is None:
            continue
        starts.append((i, qno))

    if not starts:
        return [(None, "\n".join(lines).strip())]

    chunks: list[tuple[int | None, str]] = []
    for idx, (start_i, qno) in enumerate(starts):
        end_i = starts[idx + 1][0] if idx + 1 < len(starts) else len(lines)
        chunk = "\n".join(lines[start_i:end_i]).strip()
        if chunk:
            chunks.append((qno, chunk))
    return chunks


def _next_available_index(used_indices: set[int], preferred: int) -> int:
    candidate = max(1, int(preferred))
    while candidate in used_indices:
        candidate += 1
    used_indices.add(candidate)
    return candidate


def _safe_split_equal_vertical_image(
    source_image_path: str,
    out_dir: Path,
    split_count: int,
    base_index: int,
) -> list[str]:
    if split_count <= 1:
        return [source_image_path]
    try:
        from PIL import Image
    except Exception:
        return [source_image_path]

    try:
        with Image.open(source_image_path) as img:
            width, height = img.size
            if height <= split_count * 8:
                return [source_image_path]

            out_paths: list[str] = []
            for i in range(split_count):
                y0 = int(round(height * (i / split_count)))
                y1 = int(round(height * ((i + 1) / split_count)))
                if y1 <= y0 + 2:
                    continue
                cropped = img.crop((0, y0, width, y1))
                out_path = out_dir / f"ocr_split_{base_index:03d}_{i + 1:02d}.png"
                cropped.save(out_path)
                out_paths.append(str(out_path))
            return out_paths or [source_image_path]
    except Exception:
        return [source_image_path]


def _resolve_column_question_counts(
    total_count: int,
    left_detected: int,
    right_detected: int,
) -> tuple[int, int]:
    total = max(1, int(total_count))
    left_detected = max(0, int(left_detected))
    right_detected = max(0, int(right_detected))

    if left_detected > 0 and right_detected > 0:
        detected_sum = left_detected + right_detected
        if detected_sum == total:
            return left_detected, right_detected
        if detected_sum > 0:
            left = max(1, min(total - 1, int(round(total * (left_detected / detected_sum)))))
            return left, total - left

    left = (total + 1) // 2
    right = total - left
    if right == 0:
        return total, 0
    return left, right


def _safe_count_questions_in_pil_image(image, ocr_lang: str = "kor+eng") -> int:
    try:
        import pytesseract
    except Exception:
        return 0
    try:
        text = _ocr_from_single_region(pytesseract, image, ocr_lang=ocr_lang)
    except Exception:
        return 0
    chunks = _split_ocr_text_by_question_starts(text)
    return len(chunks)


def _save_vertical_splits_from_pil_image(
    image,
    out_dir: Path,
    split_count: int,
    prefix: str,
) -> list[str]:
    if split_count <= 0:
        return []
    width, height = image.size
    if height <= split_count * 8:
        return []

    out_paths: list[str] = []
    for i in range(split_count):
        y0 = int(round(height * (i / split_count)))
        y1 = int(round(height * ((i + 1) / split_count)))
        if y1 <= y0 + 2:
            continue
        cropped = image.crop((0, y0, width, y1))
        out_path = out_dir / f"{prefix}_{i + 1:02d}.png"
        cropped.save(out_path)
        out_paths.append(str(out_path))
    return out_paths


def expand_question_images_for_ocr_synthetic_questions(
    module5,
    question_images,
    question_texts,
):
    image_by_index = {int(item.index): item for item in question_images}
    text_indices = sorted(int(item.index) for item in question_texts)
    if not text_indices:
        return question_images

    existing_indices = sorted(image_by_index.keys())
    if not existing_indices:
        return question_images

    out_by_index: dict[int, object] = {int(item.index): item for item in question_images}
    for pos, base_index in enumerate(existing_indices):
        next_index = existing_indices[pos + 1] if pos + 1 < len(existing_indices) else None
        group_indices = [
            idx for idx in text_indices if idx >= base_index and (next_index is None or idx < next_index)
        ]
        if len(group_indices) <= 1:
            continue

        base_item = image_by_index[base_index]
        if len(base_item.problem_image_paths) != 1 or base_item.choices_image_paths:
            continue

        source_path = base_item.problem_image_paths[0]
        out_dir = Path(source_path).resolve().parent
        split_paths: list[str] = []
        try:
            from PIL import Image
            with Image.open(source_path) as src_img:
                separator_x = detect_vertical_separator_x_in_image(src_img)
                if separator_x is not None:
                    width, height = src_img.size
                    sep = int(separator_x)
                    gap = max(8, int(width * 0.015))
                    left_img = src_img.crop((0, 0, max(1, sep - gap), height))
                    right_img = src_img.crop((min(width - 1, sep + gap), 0, width, height))

                    left_detected = _safe_count_questions_in_pil_image(left_img)
                    right_detected = _safe_count_questions_in_pil_image(right_img)
                    left_count, right_count = _resolve_column_question_counts(
                        total_count=len(group_indices),
                        left_detected=left_detected,
                        right_detected=right_detected,
                    )
                    left_paths = _save_vertical_splits_from_pil_image(
                        image=left_img,
                        out_dir=out_dir,
                        split_count=left_count,
                        prefix=f"ocr_split_{base_index:03d}_L",
                    )
                    right_paths = _save_vertical_splits_from_pil_image(
                        image=right_img,
                        out_dir=out_dir,
                        split_count=right_count,
                        prefix=f"ocr_split_{base_index:03d}_R",
                    )
                    split_paths = left_paths + right_paths
        except Exception:
            split_paths = []

        if not split_paths:
            split_paths = _safe_split_equal_vertical_image(
                source_image_path=source_path,
                out_dir=out_dir,
                split_count=len(group_indices),
                base_index=base_index,
            )
        if len(split_paths) != len(group_indices):
            continue

        for i, idx in enumerate(group_indices):
            out_by_index[idx] = module5.QuestionImageSet(
                index=idx,
                qno=None,
                problem_image_paths=[split_paths[i]],
                choices_image_paths=[],
            )

    return [out_by_index[idx] for idx in sorted(out_by_index.keys())]


def _trim_chunks_from_expected_qno(
    chunks: list[tuple[int | None, str]],
    expected_qno: int | None,
) -> list[tuple[int | None, str]]:
    if expected_qno is None:
        return chunks
    for i, (qno, _chunk) in enumerate(chunks):
        if qno == expected_qno:
            return chunks[i:]
    return chunks


def _normalize_nearly_consecutive_qnos(
    chunks: list[tuple[int | None, str]],
) -> list[tuple[int | None, str]]:
    qnos = [qno for qno, _ in chunks]
    if len(qnos) < 6:
        return chunks
    if any(qno is None for qno in qnos):
        return chunks

    nums = [int(qno) for qno in qnos if qno is not None]
    if nums[0] != 1:
        return chunks
    if any(nums[i] <= nums[i - 1] for i in range(1, len(nums))):
        return chunks

    expected = list(range(nums[0], nums[0] + len(nums)))
    mismatch_indices = [i for i, (a, b) in enumerate(zip(nums, expected)) if a != b]
    if not mismatch_indices:
        return chunks

    # OCR 숫자 오인식으로 중간부터 +1로 밀린 케이스(예: 1..6,8..13)를 보정한다.
    first_mismatch = mismatch_indices[0]
    shifted = all(nums[i] == (expected[i] + 1) for i in range(first_mismatch, len(nums)))
    if shifted:
        return [(expected[i], text) for i, (_, text) in enumerate(chunks)]

    return chunks


def _extract_ocr_question_block(text: str, expected_qno: int | None) -> str:
    lines = [line.rstrip() for line in (text or "").splitlines()]
    if not lines:
        return ""

    start_idx = 0
    if expected_qno is not None:
        for i, line in enumerate(lines):
            qno = _parse_ocr_qno_from_line(line)
            if qno == expected_qno:
                start_idx = i
                break
    else:
        for i, line in enumerate(lines):
            if _is_ocr_question_start_line(line):
                start_idx = i
                break

    question_lines: list[str] = []
    choice_count = 0
    for line in lines[start_idx:]:
        if question_lines and _is_ocr_question_start_line(line) and choice_count >= 3:
            break
        if OCR_CHOICE_LINE_RE.match(line) and not _is_ocr_question_start_line(line):
            choice_count += 1
        question_lines.append(line)

    return "\n".join(question_lines).strip()


def _split_ocr_question_and_choices(text: str) -> tuple[str, str]:
    lines = [line.rstrip() for line in (text or "").splitlines()]
    if not lines:
        return "", ""

    first_choice_index = None
    for i, line in enumerate(lines):
        if OCR_CHOICE_LINE_RE.match(line) and not _is_ocr_question_start_line(line):
            first_choice_index = i
            break

    if first_choice_index is None:
        return "\n".join(lines).strip(), ""

    question_text = "\n".join(lines[:first_choice_index]).strip()
    choices_text = "\n".join(lines[first_choice_index:]).strip()
    return question_text, choices_text


def ocr_text_from_image_paths(image_paths, ocr_lang: str = "kor+eng") -> str:
    try:
        import pytesseract
        from PIL import Image
    except Exception:
        _warn_ocr_once(
            "ocr_python_deps_missing",
            "[OCR] pytesseract/Pillow를 불러오지 못했습니다. "
            "OCR을 건너뜁니다. (pip install pytesseract pillow)",
        )
        return ""

    if shutil.which("tesseract") is None:
        _warn_ocr_once(
            "ocr_tesseract_missing",
            "[OCR] tesseract 실행 파일을 찾지 못했습니다. "
            "OCR을 건너뜁니다. (macOS: brew install tesseract tesseract-lang)",
        )
        return ""

    ocr_parts = []
    for image_path in image_paths:
        try:
            with Image.open(image_path) as img:
                ocr_text = _ocr_from_single_image(pytesseract, img, ocr_lang=ocr_lang)
        except Exception as exc:
            _warn_ocr_once(
                "ocr_runtime_error",
                f"[OCR] OCR 처리 중 오류가 발생했습니다: {type(exc).__name__}. "
                "해당 이미지 OCR을 건너뜁니다.",
            )
            ocr_text = ""
        if ocr_text and ocr_text.strip():
            ocr_parts.append(ocr_text.strip())

    return "\n".join(ocr_parts).strip()


def enhance_question_texts_with_ocr(
    module5,
    question_images,
    question_texts,
    min_chars: int = 30,
    ocr_lang: str = "kor+eng",
):
    image_by_index = {item.index: item for item in question_images}
    used_indices = {int(item.index) for item in question_texts}
    out = []
    for item in question_texts:
        combined_text = _build_combined_text(item.question_text, item.choices_text)
        if not should_use_ocr_fallback(combined_text, min_chars=min_chars):
            out.append(item)
            continue

        image_item = image_by_index.get(item.index)
        if image_item is None:
            out.append(item)
            continue

        image_paths = list(image_item.problem_image_paths) + list(image_item.choices_image_paths)
        if not image_paths:
            out.append(item)
            continue

        ocr_text = ocr_text_from_image_paths(image_paths=image_paths, ocr_lang=ocr_lang)
        if not ocr_text:
            out.append(item)
            continue

        chunks = _trim_chunks_from_expected_qno(
            _split_ocr_text_by_question_starts(ocr_text),
            expected_qno=item.qno,
        )
        if len(chunks) <= 1:
            ocr_text = _extract_ocr_question_block(ocr_text, expected_qno=item.qno)
            chunks = _split_ocr_text_by_question_starts(ocr_text)
        chunks = _normalize_nearly_consecutive_qnos(chunks)
        if not chunks:
            out.append(item)
            continue

        for chunk_idx, (chunk_qno, chunk_text) in enumerate(chunks):
            question_text, choices_text = _split_pre_shared_text(module5, chunk_text)
            ocr_question_text, ocr_choices_text = _split_ocr_question_and_choices(chunk_text)
            if not choices_text:
                question_text, choices_text = ocr_question_text, ocr_choices_text
            elif _should_prefer_ocr_split(
                primary_question_text=question_text,
                primary_choices_text=choices_text,
                ocr_question_text=ocr_question_text,
                ocr_choices_text=ocr_choices_text,
            ):
                question_text, choices_text = ocr_question_text, ocr_choices_text

            if chunk_idx == 0:
                target_index = item.index
                used_indices.add(int(target_index))
                target_qno = item.qno if item.qno is not None else chunk_qno
            else:
                target_index = _next_available_index(used_indices, preferred=item.index + chunk_idx)
                target_qno = chunk_qno

            question_text = _normalize_question_text_leading_number(question_text, target_qno)
            question_text = _normalize_common_ocr_phrases(question_text)
            choices_text = _normalize_common_ocr_phrases(choices_text)

            out.append(
                module5.QuestionTextSet(
                    index=target_index,
                    qno=target_qno,
                    question_text=question_text,
                    choices_text=choices_text,
                )
            )
    return sorted(out, key=lambda x: int(x.index))


def normalize_text_for_hash(text: str) -> str:
    return " ".join((text or "").split())


def build_db_ready_records(
    pdf_path: str,
    target_dir: Path,
    question_images,
    question_texts,
    shared_passages: List[SharedPassageSet],
    shared_map: dict[int, str],
):
    source_pdf_name = Path(pdf_path).name
    source_pdf_stem = Path(pdf_path).stem
    image_by_index = {item.index: item for item in question_images}
    text_by_index = {item.index: item for item in question_texts}
    shared_by_id = {item.passage_id: item for item in shared_passages}

    def _relpath(path: str) -> str:
        return os.path.relpath(path, start=target_dir)

    records = []
    for index in sorted(set(image_by_index.keys()) | set(text_by_index.keys())):
        image_item = image_by_index.get(index)
        text_item = text_by_index.get(index)

        question_number = None
        if text_item is not None:
            question_number = text_item.qno
        elif image_item is not None:
            question_number = image_item.qno

        question_text = text_item.question_text if text_item is not None else ""
        choices_text = text_item.choices_text if text_item is not None else ""

        shared_passage_id = None
        if question_number is not None:
            shared_passage_id = shared_map.get(question_number)
        shared_item = shared_by_id.get(shared_passage_id) if shared_passage_id is not None else None

        shared_passage_text = shared_item.text if shared_item is not None else None
        shared_passage_image_paths = (
            [_relpath(path) for path in shared_item.image_paths] if shared_item is not None else []
        )

        problem_image_paths = (
            [_relpath(path) for path in image_item.problem_image_paths]
            if image_item is not None
            else []
        )
        choices_image_paths = (
            [_relpath(path) for path in image_item.choices_image_paths]
            if image_item is not None
            else []
        )

        normalized = normalize_text_for_hash(
            f"{question_text}\n{choices_text}\n{shared_passage_text or ''}"
        )
        content_hash = hashlib.sha1(normalized.encode("utf-8")).hexdigest()
        qno_part = str(question_number) if question_number is not None else "na"
        record_id = f"{source_pdf_stem}:{index:03d}:{qno_part}:{content_hash[:12]}"

        records.append(
            {
                "schema_version": "v1",
                "record_id": record_id,
                "source_pdf_name": source_pdf_name,
                "source_pdf_stem": source_pdf_stem,
                "question_index": index,
                "question_number": question_number,
                "question_text": question_text,
                "choices_text": choices_text,
                "shared_passage_id": shared_passage_id,
                "shared_passage_text": shared_passage_text,
                "problem_image_paths": problem_image_paths,
                "choices_image_paths": choices_image_paths,
                "shared_passage_image_paths": shared_passage_image_paths,
                "content_hash": content_hash,
            }
        )

    return records


def save_db_ready_jsonl(out_dir: Path | str, records) -> Path:
    out_dir_path = Path(out_dir)
    out_dir_path.mkdir(parents=True, exist_ok=True)
    out_path = out_dir_path / "questions_db_ready.jsonl"
    with out_path.open("w", encoding="utf-8") as fp:
        for record in records:
            fp.write(json.dumps(record, ensure_ascii=False) + "\n")
    return out_path


def render_pdf_questions_with_text(
    module5,
    *,
    pdf_path: str,
    image_dir: str,
    dpi: int = 200,
):
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
    # 고정 footer margin으로 페이지 하단 실제 선택지가 잘리는 케이스가 있어
    # 하단 여백 컷은 비활성화하고, 대신 노이즈 블록 필터가 footer/banner를 제거하도록 한다.
    footer_margin = 0.0

    with fitz.open(pdf_path) as doc:
        page_columns = module5.detect_page_columns(doc)
        page_heights = [float(page.rect.height) for page in doc]
        starts = module5.get_question_starts(doc, page_columns=page_columns)
        spans = module5.build_question_spans(starts, page_heights, page_columns=page_columns)

        if not spans:
            page_images = module5.render_pdf_pages_to_png(doc, image_dir=image_dir, dpi=dpi)
            question_images = [
                module5.QuestionImageSet(
                    index=i + 1,
                    qno=None,
                    problem_image_paths=[path],
                    choices_image_paths=[],
                )
                for i, path in enumerate(page_images)
            ]
            question_texts = []
            for i, page in enumerate(doc, start=1):
                raw_text = (page.get_text("text") or "").strip()
                question_text, choices_text = module5.split_question_and_choices(raw_text)
                question_texts.append(
                    module5.QuestionTextSet(
                        index=i,
                        qno=None,
                        question_text=question_text,
                        choices_text=choices_text,
                    )
                )
            return question_images, question_texts

        question_images = []
        question_texts = []
        for span in spans:
            problem_paths: list[str] = []
            choices_paths: list[str] = []
            question_text_parts: list[str] = []
            choices_text_parts: list[str] = []
            choices_started = False

            for segment_part, segment in enumerate(span.segments, start=1):
                page = doc.load_page(segment.page_index)
                page_width = float(page.rect.width)
                page_height = float(page.rect.height)
                col_x0, col_x1 = module5.expand_column_bounds(
                    columns=page_columns[segment.page_index],
                    column_index=segment.column,
                    page_width=page_width,
                )

                raw_y0, raw_y1 = module5.compute_raw_clip_bounds(
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

                raw_blocks = collect_text_blocks_with_text_for_clip(
                    page,
                    clip_x0=clip_x0,
                    clip_x1=clip_x1,
                    raw_y0=raw_y0,
                    raw_y1=raw_y1,
                )
                filtered_raw_blocks = filter_page_noise_blocks(raw_blocks, page_height=page_height)
                if not filtered_raw_blocks:
                    continue

                text_boxes = [(x0, y0, x1, y1) for x0, y0, x1, y1, _text in filtered_raw_blocks]
                y0, y1 = module5.refine_clip_y_to_text_blocks(
                    raw_y0=raw_y0,
                    raw_y1=raw_y1,
                    text_block_boxes=text_boxes,
                )
                clip_x0, clip_x1 = module5.refine_clip_x_to_text_blocks(
                    raw_x0=clip_x0,
                    raw_x1=clip_x1,
                    text_block_boxes=text_boxes,
                )

                filtered_blocks = filter_page_noise_blocks(
                    collect_text_blocks_with_text_for_clip(
                        page,
                        clip_x0=clip_x0,
                        clip_x1=clip_x1,
                        raw_y0=y0,
                        raw_y1=y1,
                    ),
                    page_height=page_height,
                )
                if not filtered_blocks:
                    continue

                clip_text = _join_text_from_blocks(filtered_blocks)
                if not clip_text:
                    continue

                incoming_choices_started = choices_started
                problem_clip_y, choices_clip_y, choices_started = resolve_segment_clips_for_state(
                    clip_y0=y0,
                    clip_y1=y1,
                    text_blocks=filtered_blocks,
                    choices_started=choices_started,
                    split_clip_fn=module5.split_problem_and_choices_clip_by_choice_blocks,
                )

                question_text_part, choices_text_part, choices_started = split_segment_text_for_state(
                    module5,
                    clip_text=clip_text,
                    choices_started=incoming_choices_started,
                )

                if question_text_part:
                    question_text_parts.append(question_text_part)
                if choices_text_part:
                    choices_text_parts.append(choices_text_part)

                if problem_clip_y is not None:
                    problem_clip = fitz.Rect(clip_x0, problem_clip_y[0], clip_x1, problem_clip_y[1])
                    pix = page.get_pixmap(matrix=matrix, clip=problem_clip, alpha=False)
                    out_path = image_dir_path / (
                        f"question_{span.index:03d}_problem_part_{len(problem_paths) + 1:02d}.png"
                    )
                    pix.save(out_path)
                    problem_paths.append(str(out_path))

                if choices_clip_y is not None:
                    choices_clip = fitz.Rect(clip_x0, choices_clip_y[0], clip_x1, choices_clip_y[1])
                    pix = page.get_pixmap(matrix=matrix, clip=choices_clip, alpha=False)
                    out_path = image_dir_path / (
                        f"question_{span.index:03d}_choices_part_{len(choices_paths) + 1:02d}.png"
                    )
                    pix.save(out_path)
                    choices_paths.append(str(out_path))

            if problem_paths or choices_paths:
                sequence_index = len(question_images) + 1
                question_images.append(
                    module5.QuestionImageSet(
                        index=sequence_index,
                        qno=span.qno,
                        problem_image_paths=problem_paths,
                        choices_image_paths=choices_paths,
                    )
                )
                question_texts.append(
                    module5.QuestionTextSet(
                        index=sequence_index,
                        qno=span.qno,
                        question_text="\n".join(question_text_parts).strip(),
                        choices_text="\n".join(choices_text_parts).strip(),
                    )
                )

    return question_images, question_texts


def process_one_pdf(
    module5,
    pdf_path: str,
    output_root: Path,
    dpi: int,
    *,
    enable_refine: bool,
    enable_ocr: bool,
    enable_db_ready: bool,
) -> Path:
    target_dir, image_dir, text_dir, out_tex = prepare_output_paths(pdf_path, output_root)
    target_dir.mkdir(parents=True, exist_ok=True)

    question_images, question_texts = render_pdf_questions_with_text(
        module5,
        pdf_path=str(pdf_path),
        image_dir=str(image_dir),
        dpi=dpi,
    )

    (
        question_images,
        question_texts,
        shared_passages,
        shared_map,
    ) = extract_shared_passages(
        module5=module5,
        question_images=question_images,
        question_texts=question_texts,
        image_dir=image_dir,
    )
    if enable_ocr:
        question_texts = enhance_question_texts_with_ocr(
            module5=module5,
            question_images=question_images,
            question_texts=question_texts,
            min_chars=30,
            ocr_lang="kor+eng",
        )
        question_images = expand_question_images_for_ocr_synthetic_questions(
            module5=module5,
            question_images=question_images,
            question_texts=question_texts,
        )
    refine_available = enable_refine and is_image_refine_available()
    refined_count = 0
    if refine_available:
        refined_count = refine_rendered_image_paths(
            collect_output_image_paths(
                question_images=question_images,
                shared_passages=shared_passages,
            )
        )

    question_images_for_tex = relativize_question_images(
        module5=module5,
        question_images=question_images,
        out_tex=out_tex,
    )
    shared_passages_for_tex = relativize_shared_passages(
        shared_passages=shared_passages,
        out_tex=out_tex,
    )

    latex_content = build_latex_document(
        module5=module5,
        pdf_name=Path(pdf_path).name,
        question_images=question_images_for_tex,
        shared_passages=shared_passages_for_tex,
        shared_map=shared_map,
    )
    out_tex.write_text(latex_content, encoding="utf-8")
    save_split_texts(
        module5=module5,
        out_dir=text_dir,
        question_texts=question_texts,
        shared_passages=shared_passages,
        shared_map=shared_map,
    )
    db_ready_records = []
    db_ready_path = None
    if enable_db_ready:
        db_ready_records = build_db_ready_records(
            pdf_path=pdf_path,
            target_dir=target_dir,
            question_images=question_images,
            question_texts=question_texts,
            shared_passages=shared_passages,
            shared_map=shared_map,
        )
        db_ready_path = save_db_ready_jsonl(out_dir=text_dir, records=db_ready_records)

    print(f"[완료] {Path(pdf_path).name}")
    print(f"  - 저장 폴더: {target_dir}")
    print(f"  - LaTeX: {out_tex}")
    print(f"  - 문항 수: {len(question_images)}")
    if enable_db_ready and db_ready_path is not None:
        print(f"  - DB ready JSONL: {db_ready_path} ({len(db_ready_records)}건)")
    if shared_passages:
        print(f"  - 공통 지문 수: {len(shared_passages)}")
    if enable_refine:
        if refine_available:
            print(f"  - 경계선 refine 이미지 수: {refined_count}")
        else:
            print("  - 경계선 refine: Pillow/PyMuPDF 미설치로 건너뜀")
    return target_dir


def normalize_pdf_inputs(pdf_args: Iterable[str]) -> List[str]:
    normalized = []
    for p in pdf_args:
        path = str(Path(p).expanduser())
        if not Path(path).exists():
            raise FileNotFoundError(f"PDF not found: {path}")
        if Path(path).suffix.lower() != ".pdf":
            raise ValueError(f"PDF 파일만 처리할 수 있습니다: {path}")
        normalized.append(path)
    return normalized


def main(*, enable_refine: bool, enable_ocr: bool, enable_db_ready: bool) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--pdf",
        nargs="*",
        default=None,
        help="처리할 PDF 경로들. 생략하면 GUI로 선택",
    )
    parser.add_argument("--dpi", type=int, default=200, help="Render DPI (default: 200)")
    args = parser.parse_args()

    module5 = load_module_5()
    apply_render_safety_patches(module5)
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    if args.pdf:
        pdf_files = normalize_pdf_inputs(args.pdf)
    else:
        pdf_files = normalize_pdf_inputs(select_pdf_files_with_gui())

    if not pdf_files:
        print("선택된 PDF가 없습니다. 종료합니다.")
        return

    saved_dirs: List[Path] = []
    for pdf_path in pdf_files:
        saved_dir = process_one_pdf(
            module5,
            pdf_path=pdf_path,
            output_root=OUTPUT_ROOT,
            dpi=args.dpi,
            enable_refine=enable_refine,
            enable_ocr=enable_ocr,
            enable_db_ready=enable_db_ready,
        )
        saved_dirs.append(saved_dir)

    print("\n전체 작업 완료")
    print(f"- 처리한 PDF 수: {len(saved_dirs)}")
    print(f"- 출력 루트: {OUTPUT_ROOT.resolve()}")


if __name__ == "__main__":
    main(enable_refine=True, enable_ocr=True, enable_db_ready=True)
