#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Usage:
  python ./2_extract_all_text_and_print.py --pdf ./level2.pdf

Notes:
- 모든 페이지의 텍스트를 추출해 페이지 단위로 출력합니다.
- 수식/기호 표현 개선을 위해 PyMuPDF 레이아웃 기반 추출을 우선 시도합니다.
- PyMuPDF 실패 시 1_extract_text_and_print.py의 기본 추출 로직으로 fallback 합니다.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
from pathlib import Path
from typing import List, Tuple


def load_base_module():
    base_path = Path(__file__).resolve().parent / "1_extract_text_and_print.py"
    module_name = "extract_base_module"
    spec = importlib.util.spec_from_file_location(module_name, str(base_path))
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def extract_text_pymupdf_layout(pdf_path: str, page_indices: List[int]) -> List[Tuple[int, str]]:
    import fitz

    results: List[Tuple[int, str]] = []
    doc = fitz.open(pdf_path)
    try:
        for pi in page_indices:
            page = doc.load_page(pi)
            text_dict = page.get_text("dict", sort=True)
            out_lines: List[str] = []

            for block in text_dict.get("blocks", []):
                if block.get("type") != 0:
                    continue

                for line in block.get("lines", []):
                    spans = line.get("spans", [])
                    if not spans:
                        continue

                    parts: List[str] = []
                    prev_x1 = None
                    for span in spans:
                        span_text = span.get("text", "")
                        if not span_text:
                            continue

                        x0 = span.get("bbox", [0, 0, 0, 0])[0]
                        if prev_x1 is not None and x0 - prev_x1 > 1.5:
                            parts.append(" ")

                        parts.append(span_text)
                        prev_x1 = span.get("bbox", [0, 0, 0, 0])[2]

                    line_text = "".join(parts).strip()
                    if line_text:
                        out_lines.append(line_text)

                if out_lines and out_lines[-1] != "":
                    out_lines.append("")

            results.append((pi, "\n".join(out_lines).strip()))
    finally:
        doc.close()

    return results


def extract_all_text(pdf_path: str) -> List[Tuple[int, str]]:
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    base_module = load_base_module()

    # 먼저 페이지 수를 얻는다.
    page_count = None
    if importlib.util.find_spec("fitz") is not None:
        try:
            import fitz

            with fitz.open(pdf_path) as doc:
                page_count = doc.page_count
        except Exception:
            page_count = None

    if page_count is None and importlib.util.find_spec("pdfplumber") is not None:
        try:
            import pdfplumber

            with pdfplumber.open(pdf_path) as pdf:
                page_count = len(pdf.pages)
        except Exception:
            page_count = None

    if page_count is None and importlib.util.find_spec("pypdf") is not None:
        try:
            from pypdf import PdfReader

            page_count = len(PdfReader(pdf_path).pages)
        except Exception:
            page_count = None

    if page_count is None:
        raise RuntimeError("페이지 수를 확인할 수 없습니다. fitz/pdfplumber/pypdf 설치 상태를 확인하세요.")

    page_indices = list(range(page_count))

    # 수식/레이아웃 보존을 위해 PyMuPDF 레이아웃 추출을 우선 시도.
    if importlib.util.find_spec("fitz") is not None:
        try:
            return extract_text_pymupdf_layout(pdf_path, page_indices)
        except Exception:
            pass

    # 기존 파일의 추출 우선순위 로직 재사용.
    return base_module.extract_text(pdf_path, page_indices)


def format_all_text_output(page_texts: List[Tuple[int, str]]) -> str:
    rendered: List[str] = []
    for page_idx, raw_text in page_texts:
        text = raw_text.strip()
        rendered.append("=" * 100)
        rendered.append(f"[Page {page_idx + 1}]")
        rendered.append("-" * 100)
        rendered.append(text if text else "(텍스트 없음)")
        rendered.append("")

    return "\n".join(rendered).rstrip() + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", required=True, help="PDF file path")
    args = parser.parse_args()

    page_texts = extract_all_text(args.pdf)
    output = format_all_text_output(page_texts)
    print(output, end="")

    empty_pages = sum(1 for _, t in page_texts if not t.strip())
    if empty_pages == len(page_texts):
        print(
            "WARNING: 모든 페이지의 텍스트가 비어 있습니다. 스캔본이면 OCR이 필요합니다.",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
