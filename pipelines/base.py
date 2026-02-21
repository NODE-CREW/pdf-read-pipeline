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


@dataclass
class SharedPassageSet:
    passage_id: str
    start_qno: int
    end_qno: int
    text: str
    image_paths: List[str]


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
    return len(normalize_text_for_hash(text)) < int(min_chars)


def ocr_text_from_image_paths(image_paths, ocr_lang: str = "kor+eng") -> str:
    try:
        import pytesseract
        from PIL import Image
    except Exception:
        return ""

    ocr_parts = []
    for image_path in image_paths:
        try:
            with Image.open(image_path) as img:
                ocr_text = pytesseract.image_to_string(img, lang=ocr_lang)
        except Exception:
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

        question_text, choices_text = _split_pre_shared_text(module5, ocr_text)
        out.append(
            module5.QuestionTextSet(
                index=item.index,
                qno=item.qno,
                question_text=question_text,
                choices_text=choices_text,
            )
        )
    return out


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

    question_images, question_texts = module5._render_pdf_questions_with_text(
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
