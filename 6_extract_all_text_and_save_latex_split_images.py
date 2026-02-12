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
import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from typing import Iterable, List


OUTPUT_ROOT = Path("./output")


def load_module_5():
    module_name = "extract_latex_split_images_module"
    module_path = Path(__file__).resolve().parent / "5_extract_all_text_and_save_latex_split_images.py"

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


def process_one_pdf(module5, pdf_path: str, output_root: Path, dpi: int) -> Path:
    target_dir, image_dir, text_dir, out_tex = prepare_output_paths(pdf_path, output_root)
    target_dir.mkdir(parents=True, exist_ok=True)

    question_images, question_texts = module5._render_pdf_questions_with_text(
        pdf_path=str(pdf_path),
        image_dir=str(image_dir),
        dpi=dpi,
    )

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

    latex_content = module5.build_latex_document(
        pdf_name=Path(pdf_path).name,
        question_images=question_images_for_tex,
    )
    out_tex.write_text(latex_content, encoding="utf-8")
    module5.save_split_texts(text_dir, question_texts)

    print(f"[완료] {Path(pdf_path).name}")
    print(f"  - 저장 폴더: {target_dir}")
    print(f"  - LaTeX: {out_tex}")
    print(f"  - 문항 수: {len(question_images)}")
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


def main() -> None:
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
        saved_dir = process_one_pdf(module5, pdf_path=pdf_path, output_root=OUTPUT_ROOT, dpi=args.dpi)
        saved_dirs.append(saved_dir)

    print("\n전체 작업 완료")
    print(f"- 처리한 PDF 수: {len(saved_dirs)}")
    print(f"- 출력 루트: {OUTPUT_ROOT.resolve()}")


if __name__ == "__main__":
    main()
