#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Usage:
  python ./1_extract_text_and_print.py --pdf ./test.pdf --pages "1-3"

Notes:
- pages are 1-based in CLI (human-friendly). Internally converted to 0-based.
- Requires at least ONE: pymupdf (fitz) or pdfplumber or pypdf
- Recommended: pymupdf
- Prints questions separated by clear dividers.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import importlib.util
from dataclasses import dataclass
from typing import Iterable, List, Tuple, Optional


# -----------------------------
# Page parsing helpers
# -----------------------------

def parse_pages(pages_spec: str) -> List[int]:
    """
    Convert "1,3-5,10" to sorted unique 0-based page indices: [0,2,3,4,9]
    """
    pages_spec = pages_spec.strip()
    if not pages_spec:
        raise ValueError("Empty --pages spec")

    out = set()
    parts = [p.strip() for p in pages_spec.split(",") if p.strip()]
    for part in parts:
        if "-" in part:
            a, b = part.split("-", 1)
            a, b = int(a.strip()), int(b.strip())
            if a <= 0 or b <= 0:
                raise ValueError("Pages must be >= 1 (1-based).")
            if b < a:
                a, b = b, a
            for p in range(a, b + 1):
                out.add(p - 1)
        else:
            p = int(part)
            if p <= 0:
                raise ValueError("Pages must be >= 1 (1-based).")
            out.add(p - 1)

    return sorted(out)


def extract_text_pymupdf(pdf_path: str, page_indices: List[int]) -> List[Tuple[int, str]]:
    """
    Extract text for selected pages using PyMuPDF (fitz).
    Returns list of (page_index_0based, text).
    """
    import fitz  # PyMuPDF

    doc = fitz.open(pdf_path)
    results: List[Tuple[int, str]] = []
    try:
        max_page = doc.page_count
        for pi in page_indices:
            if pi < 0 or pi >= max_page:
                raise IndexError(f"Page out of range: {pi+1} (PDF has {max_page} pages)")
            page = doc.load_page(pi)
            # "text" gives a decent reading order for most PDFs
            text = page.get_text("text") or ""
            results.append((pi, text))
    finally:
        doc.close()
    return results


def extract_text_pdfplumber(pdf_path: str, page_indices: List[int]) -> List[Tuple[int, str]]:
    """
    Extract text for selected pages using pdfplumber.
    Returns list of (page_index_0based, text).
    """
    import pdfplumber

    results: List[Tuple[int, str]] = []
    with pdfplumber.open(pdf_path) as pdf:
        max_page = len(pdf.pages)
        for pi in page_indices:
            if pi < 0 or pi >= max_page:
                raise IndexError(f"Page out of range: {pi+1} (PDF has {max_page} pages)")
            page = pdf.pages[pi]
            text = page.extract_text() or ""
            results.append((pi, text))
    return results


def extract_text(pdf_path: str, page_indices: List[int]) -> List[Tuple[int, str]]:
    """Extract text for selected pages.

    Priority:
      1) PyMuPDF (package: pymupdf, import: fitz)
      2) pdfplumber (package: pdfplumber)
      3) pypdf (package: pypdf)

    This function is defensive against missing optional dependencies.
    """

    # Fail fast on wrong path: don't confuse missing file with missing libraries
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(
            f"PDF not found: {pdf_path!r}. "
            "Tip: pass an absolute path, or run from the directory where the PDF exists."
        )

    errors: List[str] = []

    # 1) PyMuPDF
    if importlib.util.find_spec("fitz") is not None:
        try:
            return extract_text_pymupdf(pdf_path, page_indices)
        except Exception as e:
            errors.append(f"- PyMuPDF error: {e}")
    else:
        errors.append("- PyMuPDF error: No module named 'fitz' (install: python -m pip install pymupdf)")

    # 2) pdfplumber
    if importlib.util.find_spec("pdfplumber") is not None:
        try:
            return extract_text_pdfplumber(pdf_path, page_indices)
        except Exception as e:
            errors.append(f"- pdfplumber error: {e}")
    else:
        errors.append("- pdfplumber error: No module named 'pdfplumber' (install: python -m pip install pdfplumber)")

    # 3) pypdf
    if importlib.util.find_spec("pypdf") is not None:
        try:
            from pypdf import PdfReader

            reader = PdfReader(pdf_path)
            max_page = len(reader.pages)
            results: List[Tuple[int, str]] = []
            for pi in page_indices:
                if pi < 0 or pi >= max_page:
                    raise IndexError(f"Page out of range: {pi+1} (PDF has {max_page} pages)")
                text = reader.pages[pi].extract_text() or ""
                results.append((pi, text))
            return results
        except Exception as e:
            errors.append(f"- pypdf error: {e}")
    else:
        errors.append("- pypdf error: No module named 'pypdf' (install: python -m pip install pypdf)")

    raise RuntimeError(
        "Failed to extract text with PyMuPDF, pdfplumber, and pypdf.\n"
        + "\n".join(errors)
        + "\n\n"
        + "Install at least ONE of these:\n"
        + "  - python -m pip install pymupdf\n"
        + "  - python -m pip install pdfplumber\n"
        + "  - python -m pip install pypdf\n"
    )


# -----------------------------
# Question segmentation
# -----------------------------

QUESTION_START_RE = re.compile(
    r"""
    ^\s*
    (?:
        (?:문\s*\d+)|                # 문 1
        (?:제\s*\d+\s*문)|           # 제 1 문
        (?:\d+\s*(?:번)?\s*[\.\)]?)  # 1 / 1번 / 1. / 1)
    )
    \s+
    """,
    re.VERBOSE,
)

CHOICE_LINE_RE = re.compile(r"^\s*[①②③④⑤⑥⑦⑧⑨⑩]\s*")
ALT_CHOICE_RE = re.compile(r"^\s*\(\s*[1-5]\s*\)\s*")  # (1) (2) ...


def normalize_text(text: str) -> str:
    # Normalize newlines, remove excessive whitespace but keep structure.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Replace multiple blank lines with max 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Trim trailing spaces each line
    text = "\n".join([ln.rstrip() for ln in text.split("\n")])
    return text.strip()


@dataclass
class Question:
    qno: Optional[int]
    text: str
    pages: List[int]  # 0-based page indices where content came from


def segment_questions(page_texts: List[Tuple[int, str]]) -> List[Question]:
    """
    Segment extracted texts into questions using simple heuristics.
    If question spans multiple pages, it will be merged.
    """
    # Concatenate pages with markers to track page boundaries
    # We'll keep (page_index, lines) to attribute pages to each question.
    page_lines: List[Tuple[int, List[str]]] = []
    for pi, raw in page_texts:
        norm = normalize_text(raw)
        lines = norm.split("\n") if norm else []
        page_lines.append((pi, lines))

    questions: List[Question] = []
    cur_lines: List[str] = []
    cur_pages: List[int] = []
    cur_qno: Optional[int] = None

    def flush():
        nonlocal cur_lines, cur_pages, cur_qno
        text = "\n".join([ln for ln in cur_lines if ln.strip() != ""]).strip()
        if text:
            # drop super-short junk
            questions.append(Question(qno=cur_qno, text=text, pages=sorted(set(cur_pages))))
        cur_lines = []
        cur_pages = []
        cur_qno = None

    for pi, lines in page_lines:
        for ln in lines:
            # Skip very common headers/footers patterns lightly (optional)
            # If you have specific patterns, add them here.
            if not ln.strip():
                # preserve blank line as separator
                if cur_lines and cur_lines[-1] != "":
                    cur_lines.append("")
                continue

            m = QUESTION_START_RE.match(ln)
            if m:
                # If we already have content, flush current question
                if cur_lines:
                    flush()

                # Try to parse a question number
                qno = None
                num_m = re.search(r"(\d+)", ln)
                if num_m:
                    try:
                        qno = int(num_m.group(1))
                    except ValueError:
                        qno = None

                cur_qno = qno
                cur_pages.append(pi)
                cur_lines.append(ln.strip())
                continue

            # If line looks like a choice line, keep it inside current question
            if CHOICE_LINE_RE.match(ln) or ALT_CHOICE_RE.match(ln):
                if not cur_lines:
                    # If we see choices before question start, treat as continuation junk; start bucket anyway
                    cur_pages.append(pi)
                cur_pages.append(pi)
                cur_lines.append(ln.strip())
                continue

            # Normal continuation
            if not cur_lines:
                # If we haven't started a question yet, we ignore leading noise unless it's meaningful.
                # If you want to capture preface text, remove this continue.
                continue

            cur_pages.append(pi)
            cur_lines.append(ln.strip())

    # Flush at end
    flush()

    # Post-process: merge accidental splits (e.g., when "문 1" missing but content continues)
    # Basic approach: if a question is extremely short and next doesn't have qno, merge; keep simple for now.
    merged: List[Question] = []
    i = 0
    while i < len(questions):
        q = questions[i]
        if (
            len(q.text) < 30
            and i + 1 < len(questions)
            and questions[i + 1].qno is None
        ):
            nq = questions[i + 1]
            merged.append(
                Question(
                    qno=q.qno,
                    text=(q.text + "\n" + nq.text).strip(),
                    pages=sorted(set(q.pages + nq.pages)),
                )
            )
            i += 2
            continue
        merged.append(q)
        i += 1

    return merged


# -----------------------------
# Printing
# -----------------------------

def print_questions(questions: List[Question]) -> None:
    for idx, q in enumerate(questions, start=1):
        page_str = ",".join(str(p + 1) for p in q.pages)  # back to 1-based for display
        header = f"[문제 #{idx}" + (f" | 추정번호 {q.qno}" if q.qno is not None else "") + f" | pages {page_str}]"
        passage, choices = split_passage_and_choices(q.text)

        print("=" * 100)
        print(header)
        print("-" * 100)
        print("[지문]")
        print(passage if passage else "(없음)")
        print()
        print("[선택지]")
        print(choices if choices else "(없음)")
        print()


def split_passage_and_choices(question_text: str) -> Tuple[str, str]:
    """
    Split one question text into passage and choices.
    - passage: content before the first choice marker line
    - choices: content from the first choice marker line to the end
    """
    lines = question_text.splitlines()
    first_choice_index = None

    for i, line in enumerate(lines):
        if CHOICE_LINE_RE.match(line) or ALT_CHOICE_RE.match(line):
            first_choice_index = i
            break

    if first_choice_index is None:
        return question_text.strip(), ""

    passage = "\n".join(lines[:first_choice_index]).strip()
    choices = "\n".join(lines[first_choice_index:]).strip()
    return passage, choices


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", required=True, help="PDF file path")
    ap.add_argument("--pages", required=True, help='1-based pages spec, e.g. "1,3-5,10"')
    args = ap.parse_args()

    page_indices = parse_pages(args.pages)
    page_texts = extract_text(args.pdf, page_indices)

    # If extraction yields mostly empty, warn
    empty_count = sum(1 for _, t in page_texts if not normalize_text(t))
    if empty_count == len(page_texts):
        print(
            "WARNING: Extracted text is empty for all selected pages.\n"
            "This PDF might be scanned (image-only) or protected. OCR would be needed.",
            file=sys.stderr,
        )

    questions = segment_questions(page_texts)
    if not questions:
        print(
            "No questions detected with current heuristics.\n"
            "Try adjusting QUESTION_START_RE patterns to match your exam format.",
            file=sys.stderr,
        )

    print_questions(questions)


if __name__ == "__main__":
    main()
