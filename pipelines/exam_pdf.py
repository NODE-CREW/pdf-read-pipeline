#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""시험지형 PDF의 Phase 1 텍스트 레이어 파서."""

from __future__ import annotations

import re
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import fitz

from pipelines.question_parser import (
    CHOICE_MARKER_RE,
    QUESTION_NUMBER_RE,
    _circled_to_number,
    _parse_choices_from_text,
    _strip_question_number,
)


CIRCLED_NUMBERS = "①②③④⑤⑥⑦⑧⑨⑩"
SUBJECT_PATTERNS = [
    re.compile(r"^\s*(\d+)\s*과목\s*([\.:])?\s*(.+?)\s*$"),
    re.compile(r"^\s*제\s*과목\s*(\d+)\s*([\.:])?\s*(.+?)\s*$"),
    re.compile(r"^\s*제과목\s*(\d+)\s*([\.:])?\s*(.+?)\s*$"),
    re.compile(r"^\s*제과목(\d+)\s*([\.:])?\s*(.+?)\s*$"),
    re.compile(r"^\s*제\s*과목\s+(.*\S)\s*$"),
    re.compile(r"^\s*제과목\s+(.*\S)\s*$"),
]
QUESTION_ANCHOR_RE = QUESTION_NUMBER_RE
ANSWER_PAIR_RE = re.compile(
    r"(?:^|\s)(\d{1,3})\s*[\.:)]\s*([①②③④⑤]|모두답|(?:[1-5](?:\s*,\s*[1-5])*))(?=\s|$)"
)
ANSWER_NUMBER_ROW_RE = re.compile(r"^\s*(?:\d{1,3}\s+){3,}\d{1,3}\s*$")
ANSWER_VALUE_TOKEN_RE = re.compile(r"^(?:[①②③④⑤]|\d(?:\s*,\s*\d+)*|모두답)$")
ASCII_NUMBER_RE = re.compile(r"^[0-9]{1,3}$")
PAGE_NOISE_RE = re.compile(r"^\s*-\s*\d+\s*-\s*$")
ROUND_RE = re.compile(r"^\s*\d+\s*회\s*$")


@dataclass(frozen=True)
class BBox:
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return max(0.0, self.x1 - self.x0)

    @property
    def height(self) -> float:
        return max(0.0, self.y1 - self.y0)

    @property
    def area(self) -> float:
        return self.width * self.height

    def to_list(self) -> list[float]:
        return [self.x0, self.y0, self.x1, self.y1]


@dataclass(frozen=True)
class TextBlock:
    page: int
    page_height: float
    bbox: BBox
    text: str
    column: str


@dataclass(frozen=True)
class Choice:
    label: str
    text: str


@dataclass
class Question:
    question_no: int
    subject: str | None
    page_range: tuple[int, int]
    column_range: tuple[str, str]
    stem: str
    choices: list[Choice]
    assets: list[dict[str, Any]]
    answer: str | None
    explanation: str | None
    raw_text: str
    confidence: float


def _merge_bboxes(bboxes: list[BBox]) -> BBox | None:
    if not bboxes:
        return None
    return BBox(
        x0=min(bbox.x0 for bbox in bboxes),
        y0=min(bbox.y0 for bbox in bboxes),
        x1=max(bbox.x1 for bbox in bboxes),
        y1=max(bbox.y1 for bbox in bboxes),
    )


def _pad_bbox(bbox: BBox, *, page_width: float, page_height: float, padding: float = 8.0) -> BBox:
    return BBox(
        x0=max(0.0, bbox.x0 - padding),
        y0=max(0.0, bbox.y0 - padding),
        x1=min(page_width, bbox.x1 + padding),
        y1=min(page_height, bbox.y1 + padding),
    )


def _render_question_assets(
    *,
    doc: fitz.Document,
    out_dir: Path | None,
    question_no: int,
    block_refs: list[dict[str, Any]],
    dpi: int,
) -> list[dict[str, Any]]:
    if out_dir is None or not block_refs:
        return []

    assets_dir = out_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    grouped: dict[tuple[int, str], list[BBox]] = {}
    for ref in block_refs:
        key = (ref["page"], ref["column"])
        grouped.setdefault(key, []).append(ref["bbox"])

    assets: list[dict[str, Any]] = []
    for index, ((page_no, column), bboxes) in enumerate(sorted(grouped.items()), start=1):
        merged = _merge_bboxes(bboxes)
        if merged is None:
            continue
        page = doc[page_no - 1]
        padded = _pad_bbox(
            merged,
            page_width=float(page.rect.width),
            page_height=float(page.rect.height),
        )
        clip_rect = fitz.Rect(padded.x0, padded.y0, padded.x1, padded.y1)
        zoom = dpi / 72.0
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip_rect, alpha=False)
        file_name = f"q{question_no:03d}_p{page_no:02d}_{column}_{index:02d}.png"
        output_path = assets_dir / file_name
        pix.save(output_path.as_posix())
        assets.append(
            {
                "type": "question_crop",
                "path": f"assets/{file_name}",
                "bbox": padded.to_list(),
                "page": page_no,
                "column": column,
            }
        )

    return assets


def _normalize_text(text: str) -> str:
    lines = [" ".join(line.split()) for line in (text or "").splitlines()]
    return "\n".join(line for line in lines if line).strip()


def _column_label(index: int) -> str:
    return "left" if index == 0 else "right"


def _detect_subject(text: str) -> str | None:
    normalized = _normalize_text(text)
    for pattern in SUBJECT_PATTERNS:
        match = pattern.match(normalized)
        if match:
            subject = match.group(match.lastindex).strip() if match.lastindex else ""
            subject = re.sub(r"[0-9]+", " ", subject)
            subject = re.sub(r"[:：.]", " ", subject)
            subject = " ".join(subject.split()).strip()
            return subject or None
    return None


def _is_noise_line(text: str) -> bool:
    normalized = _normalize_text(text)
    if not normalized:
        return True
    if PAGE_NOISE_RE.match(normalized) or ROUND_RE.match(normalized):
        return True
    if normalized in {"저작권 안내", "정답 및 해설", "기출문제", "-"}:
        return True
    if "기출문제" in normalized and "정답 및 해설" in normalized:
        return True
    if normalized.startswith("이 자료는 시나공 카페"):
        return True
    if normalized.startswith("다른 매체에 옮겨"):
        return True
    return False


def _bbox_overlaps(a: BBox, b: BBox) -> bool:
    return not (a.x1 <= b.x0 or a.x0 >= b.x1 or a.y1 <= b.y0 or a.y0 >= b.y1)


def _overlaps_any(bbox: BBox, others: list[BBox]) -> bool:
    return any(_bbox_overlaps(bbox, other) for other in others)


def _extract_answers_from_page(page: fitz.Page) -> tuple[dict[int, str], list[BBox], bool]:
    page_text = _normalize_text(page.get_text("text", sort=True))
    answers = parse_inline_answer_pairs(page_text)
    answer_regions: list[BBox] = []

    for row in page.get_text("blocks", sort=True):
        if len(row) < 5:
            continue
        x0, y0, x1, y1, text = row[:5]
        normalized = _normalize_text(str(text))
        if not normalized:
            continue
        block_answers = parse_inline_answer_pairs(normalized)
        block_answers.update(parse_answer_grid_block(normalized))
        if len(block_answers) >= 5:
            answers.update(block_answers)
            answer_regions.append(BBox(float(x0), float(y0), float(x1), float(y1)))

    is_full_answer_page = ("정답 및 해설" in page_text and len(answers) >= 20) or len(answers) >= 80
    return answers, answer_regions, is_full_answer_page


def _extract_column_line_refs(
    *,
    page: fitz.Page,
    rect: fitz.Rect,
    column: str,
    ignored_regions: list[BBox],
) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    text_dict = page.get_text("dict", clip=rect, sort=True)
    for block in text_dict.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            text = _normalize_text("".join(str(span.get("text", "")) for span in spans))
            if not text:
                continue
            bbox = BBox(*[float(v) for v in line.get("bbox", block.get("bbox"))])
            if _overlaps_any(bbox, ignored_regions):
                continue
            refs.append({"page": page.number + 1, "column": column, "bbox": bbox, "text": text})
    refs.sort(key=lambda ref: (round(ref["bbox"].y0 / 4.0), ref["bbox"].x0, ref["bbox"].y0))
    return refs


def _build_column_rects(page: fitz.Page, blocks: list[BBox]) -> list[tuple[str, fitz.Rect]]:
    page_width = float(page.rect.width)
    page_height = float(page.rect.height)
    anchor_xs: list[float] = []
    for block in page.get_text("dict", sort=True).get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            text = _normalize_text("".join(str(span.get("text", "")) for span in line.get("spans", [])))
            match = QUESTION_ANCHOR_RE.match(text)
            if not match:
                continue
            qno = int(match.group(1) or match.group(2))
            if 1 <= qno <= 100:
                anchor_xs.append(float(line.get("bbox", block.get("bbox"))[0]))

    if len(anchor_xs) >= 6:
        starts = sorted(anchor_xs)
        best_gap = 0.0
        separator = None
        for left, right in zip(starts, starts[1:]):
            gap = right - left
            if gap > best_gap:
                best_gap = gap
                separator = (left + right) / 2.0
        if separator is not None and best_gap >= page_width * 0.18:
            left_count = sum(1 for x in starts if x < separator)
            right_count = len(starts) - left_count
            if left_count >= 3 and right_count >= 3:
                left_blocks = [bbox for bbox in blocks if bbox.x0 < separator]
                right_blocks = [bbox for bbox in blocks if bbox.x0 >= separator]
                right_x0 = min((bbox.x0 for bbox in right_blocks), default=separator + 5.0)
                left_x1 = max((bbox.x1 for bbox in left_blocks), default=separator - 5.0)
                left_x1 = min(left_x1, right_x0 - 5.0)
                return [
                    ("left", fitz.Rect(0.0, 0.0, left_x1, page_height)),
                    ("right", fitz.Rect(right_x0, 0.0, page_width, page_height)),
                ]

    columns = detect_columns_for_blocks(blocks, page_width)
    if len(columns) == 1:
        return [("full", fitz.Rect(0.0, 0.0, page_width, page_height))]
    return [
        ("left", fitz.Rect(columns[0][0], 0.0, columns[0][1], page_height)),
        ("right", fitz.Rect(columns[1][0], 0.0, columns[1][1], page_height)),
    ]


def detect_columns_for_blocks(blocks: list[BBox], page_width: float) -> list[tuple[float, float]]:
    if len(blocks) < 4:
        return [(0.0, page_width)]

    starts = sorted(bbox.x0 for bbox in blocks if bbox.width > 0)
    if len(starts) < 4:
        return [(0.0, page_width)]

    best_gap = 0.0
    separator = None
    for left, right in zip(starts, starts[1:]):
        gap = right - left
        if gap > best_gap:
            best_gap = gap
            separator = (left + right) / 2.0

    if separator is None or best_gap < page_width * 0.15:
        return [(0.0, page_width)]

    left_count = sum(1 for bbox in blocks if (bbox.x0 + bbox.x1) / 2.0 < separator)
    right_count = len(blocks) - left_count
    if left_count < 2 or right_count < 2:
        return [(0.0, page_width)]

    if best_gap > 1.0:
        return [(0.0, separator - 0.5), (separator + 0.5, page_width)]
    return [(0.0, separator), (separator, page_width)]


def _assign_column(columns: list[tuple[float, float]], bbox: BBox) -> str:
    if len(columns) == 1:
        return "full"
    center_x = (bbox.x0 + bbox.x1) / 2.0
    return "left" if center_x < columns[1][0] else "right"


def _count_margin_texts(
    doc: fitz.Document,
    *,
    top_ratio: float = 0.12,
    bottom_ratio: float = 0.06,
) -> tuple[dict[str, int], dict[str, int]]:
    top_counts: dict[str, int] = {}
    bottom_counts: dict[str, int] = {}

    for page in doc:
        page_height = float(page.rect.height)
        top_limit = page_height * top_ratio
        bottom_limit = page_height * (1.0 - bottom_ratio)
        for row in page.get_text("blocks", sort=False):
            if len(row) < 5:
                continue
            x0, y0, x1, y1, text = row[:5]
            normalized = _normalize_text(str(text))
            if not normalized:
                continue
            if float(y1) <= top_limit:
                top_counts[normalized] = top_counts.get(normalized, 0) + 1
            if float(y0) >= bottom_limit:
                bottom_counts[normalized] = bottom_counts.get(normalized, 0) + 1

    return top_counts, bottom_counts


def _extract_page_blocks(
    page: fitz.Page,
    *,
    repeated_top_texts: set[str],
    repeated_bottom_texts: set[str],
) -> list[TextBlock]:
    page_width = float(page.rect.width)
    page_height = float(page.rect.height)
    top_limit = page_height * 0.12
    bottom_limit = page_height * (1.0 - 0.06)
    raw_blocks: list[tuple[BBox, str]] = []

    for row in page.get_text("blocks", sort=False):
        if len(row) < 5:
            continue
        x0, y0, x1, y1, text = row[:5]
        normalized = _normalize_text(str(text))
        if not normalized:
            continue
        if normalized in repeated_top_texts and float(y1) <= top_limit:
            continue
        if normalized in repeated_bottom_texts and float(y0) >= bottom_limit:
            continue
        raw_blocks.append((BBox(float(x0), float(y0), float(x1), float(y1)), normalized))

    columns = detect_columns_for_blocks([bbox for bbox, _ in raw_blocks], page_width)
    text_blocks = [
        TextBlock(
            page=page.number + 1,
            page_height=page_height,
            bbox=bbox,
            text=text,
            column=_assign_column(columns, bbox),
        )
        for bbox, text in raw_blocks
    ]
    text_blocks.sort(key=lambda block: (0 if block.column in ("full", "left") else 1, block.bbox.y0, block.bbox.x0))
    return text_blocks


def _answer_label_from_number(number: int) -> str:
    if 1 <= number <= len(CIRCLED_NUMBERS):
        return CIRCLED_NUMBERS[number - 1]
    return str(number)


def _normalize_answer_token(token: str) -> str:
    stripped = token.strip()
    if not stripped:
        return stripped
    if stripped == "모두답":
        return stripped
    if re.fullmatch(r"\d(?:\s*,\s*\d+)*", stripped):
        parts = [part.strip() for part in stripped.split(",") if part.strip()]
        return ",".join(_answer_label_from_number(int(part)) for part in parts)
    return stripped


def parse_answer_grid_block(text: str) -> dict[int, str]:
    lines = [" ".join(line.split()) for line in (text or "").splitlines() if line.strip()]
    answers: dict[int, str] = {}

    for index, line in enumerate(lines[:-1]):
        if not ANSWER_NUMBER_ROW_RE.match(line):
            continue
        number_tokens = line.split()
        answer_tokens = lines[index + 1].split()
        if len(number_tokens) != len(answer_tokens):
            continue
        if not all(ASCII_NUMBER_RE.match(token) for token in number_tokens):
            continue
        if not all(ANSWER_VALUE_TOKEN_RE.match(token) for token in answer_tokens):
            continue
        for qno, answer in zip(number_tokens, answer_tokens):
            qno_int = int(qno)
            if 1 <= qno_int <= 100:
                answers[qno_int] = _normalize_answer_token(answer)

    if answers:
        return answers

    tokens = [token for line in lines for token in line.split()]
    for index in range(0, len(tokens) - 1, 2):
        qno_token = tokens[index]
        answer_token = tokens[index + 1]
        if not ASCII_NUMBER_RE.match(qno_token):
            continue
        if not ANSWER_VALUE_TOKEN_RE.match(answer_token):
            continue
        qno_int = int(qno_token)
        if 1 <= qno_int <= 100:
            answers[qno_int] = _normalize_answer_token(answer_token)

    return answers


def parse_inline_answer_pairs(text: str) -> dict[int, str]:
    answers: dict[int, str] = {}
    for match in ANSWER_PAIR_RE.finditer(text or ""):
        qno = int(match.group(1))
        if 1 <= qno <= 100:
            answers[qno] = _normalize_answer_token(match.group(2))
    return answers


def _is_answer_block(block: TextBlock) -> bool:
    if block.bbox.y0 < block.page_height * 0.7:
        return False
    answers = parse_answer_grid_block(block.text)
    if len(answers) >= 5:
        return True
    return len(parse_inline_answer_pairs(block.text)) >= 5


def _build_choices_from_text(text: str) -> list[Choice]:
    parsed = _parse_choices_from_text(text)
    return [
        Choice(label=_answer_label_from_number(choice["number"]), text=choice["text"])
        for choice in parsed
    ]


def _normalize_stem_text(text: str) -> str:
    lines = [line.strip() for line in _normalize_text(text).splitlines() if line.strip()]
    if len(lines) >= 2 and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9\-\+/&() ]{0,12}", lines[1]) and lines[0].endswith("중"):
        lines = [f"{lines[1]} {lines[0]}", *lines[2:]]
    return "\n".join(lines).strip()


def _split_block_into_segments(text: str) -> list[str]:
    lines = [" ".join(line.split()) for line in (text or "").splitlines() if line.strip()]
    if not lines:
        return []

    segments: list[list[str]] = []
    current: list[str] = []
    previous_qno: int | None = None
    for line in lines:
        match = QUESTION_ANCHOR_RE.match(line)
        current_qno = int(match.group(1) or match.group(2)) if match else None
        should_split = (
            match is not None
            and current_qno is not None
            and current
            and previous_qno is not None
            and 0 < (current_qno - previous_qno) <= 2
        )
        if should_split:
            segments.append(current)
            current = [line]
            previous_qno = current_qno
            continue
        if match is not None and previous_qno is None and current_qno is not None:
            previous_qno = current_qno
        current.append(line)

    if current:
        segments.append(current)

    return ["\n".join(segment).strip() for segment in segments if segment]


def split_stem_and_choices(raw_text: str) -> tuple[str, list[Choice]]:
    normalized = _normalize_text(raw_text)
    first_choice = CHOICE_MARKER_RE.search(normalized)
    if not first_choice:
        return _normalize_stem_text(normalized), []
    stem = _normalize_stem_text(normalized[:first_choice.start()].strip())
    choices = _build_choices_from_text(normalized[first_choice.start():])
    return stem, choices


def _score_question(*, stem: str, choices: list[Choice], answer: str | None, raw_text: str) -> float:
    score = 1.0
    if len(choices) < 4:
        score -= 0.2
    if len(stem) < 15:
        score -= 0.15
    if not answer:
        score -= 0.15
    if len(raw_text) < 30:
        score -= 0.1
    return round(max(0.0, score), 2)


def _question_to_dict(question: Question) -> dict[str, Any]:
    data = asdict(question)
    data["page_range"] = list(question.page_range)
    data["column_range"] = list(question.column_range)
    data["choices"] = [asdict(choice) for choice in question.choices]
    return data


class ExamPDFPipeline:
    def run(self, pdf_path: Path | str, *, out_dir: Path | str | None = None, dpi: int = 150) -> dict[str, Any]:
        source = Path(pdf_path)
        resolved_out_dir = Path(out_dir) if out_dir is not None else None
        doc = fitz.open(source)
        try:
            top_counts, bottom_counts = _count_margin_texts(doc)
            repeated_top_texts = {text for text, count in top_counts.items() if count >= 2}
            repeated_bottom_texts = {text for text, count in bottom_counts.items() if count >= 2}

            answers: dict[int, str] = {}
            line_refs_by_page: list[list[dict[str, Any]]] = []
            for page in doc:
                page_answers, answer_regions, is_full_answer_page = _extract_answers_from_page(page)
                answers.update(page_answers)
                if is_full_answer_page:
                    line_refs_by_page.append([])
                    continue

                filtered_blocks: list[BBox] = []
                for row in page.get_text("blocks", sort=False):
                    if len(row) < 5:
                        continue
                    x0, y0, x1, y1, text = row[:5]
                    normalized = _normalize_text(str(text))
                    if not normalized:
                        continue
                    bbox = BBox(float(x0), float(y0), float(x1), float(y1))
                    if _overlaps_any(bbox, answer_regions):
                        continue
                    if normalized in repeated_top_texts and float(y1) <= float(page.rect.height) * 0.12:
                        continue
                    if normalized in repeated_bottom_texts and float(y0) >= float(page.rect.height) * (1.0 - 0.06):
                        continue
                    filtered_blocks.append(bbox)

                page_line_refs: list[dict[str, Any]] = []
                for column, rect in _build_column_rects(page, filtered_blocks):
                    page_line_refs.extend(
                        _extract_column_line_refs(
                            page=page,
                            rect=rect,
                            column=column,
                            ignored_regions=answer_regions,
                        )
                    )
                line_refs_by_page.append(page_line_refs)

            title = source.stem
            for text in repeated_top_texts:
                if "기출문제" in text:
                    title = text
                    break
            first_page_text = "\n".join(ref["text"] for ref in line_refs_by_page[0]) if line_refs_by_page else ""
            for line in first_page_text.splitlines():
                if "기출문제" in line:
                    title = line.strip()
                    break

            anchor_x_thresholds: dict[tuple[int, str], float] = {}
            for page_line_refs in line_refs_by_page:
                grouped: dict[tuple[int, str], list[dict[str, Any]]] = {}
                for ref in page_line_refs:
                    grouped.setdefault((ref["page"], ref["column"]), []).append(ref)
                for key, refs in grouped.items():
                    anchor_xs = [
                        ref["bbox"].x0
                        for ref in refs
                        if QUESTION_ANCHOR_RE.match(ref["text"]) and int((QUESTION_ANCHOR_RE.match(ref["text"]).group(1) or QUESTION_ANCHOR_RE.match(ref["text"]).group(2))) <= 100
                    ]
                    if anchor_xs:
                        anchor_x_thresholds[key] = statistics.median(anchor_xs)

            current_subject: str | None = None
            current_question: dict[str, Any] | None = None
            questions: list[Question] = []
            pending_subject_parts: list[str] = []

            def flush_current() -> None:
                nonlocal current_question
                if not current_question:
                    return
                raw_text = _normalize_text("\n".join(current_question["blocks"]))
                stem, choices = split_stem_and_choices(raw_text)
                qno = current_question["question_no"]
                answer = answers.get(qno)
                assets = _render_question_assets(
                    doc=doc,
                    out_dir=resolved_out_dir,
                    question_no=qno,
                    block_refs=current_question["block_refs"],
                    dpi=dpi,
                )
                question = Question(
                    question_no=qno,
                    subject=current_question["subject"],
                    page_range=(current_question["start_page"], current_question["end_page"]),
                    column_range=(current_question["start_column"], current_question["end_column"]),
                    stem=stem,
                    choices=choices,
                    assets=assets,
                    answer=answer,
                    explanation=None,
                    raw_text=raw_text,
                    confidence=_score_question(stem=stem, choices=choices, answer=answer, raw_text=raw_text),
                )
                questions.append(question)
                current_question = None

            for page_line_refs in line_refs_by_page:
                for ref in page_line_refs:
                    line_text = ref["text"]
                    if _is_noise_line(line_text):
                        continue

                    if pending_subject_parts:
                        pending_subject_parts.append(line_text)
                        merged_subject = _detect_subject(" ".join(pending_subject_parts))
                        if merged_subject:
                            current_subject = merged_subject
                            pending_subject_parts = []
                            continue
                        if len(pending_subject_parts) >= 4:
                            pending_subject_parts = []

                    subject = _detect_subject(line_text)
                    if subject:
                        current_subject = subject
                        pending_subject_parts = []
                        continue
                    if "제과목" in line_text or line_text == "제과목":
                        pending_subject_parts = [line_text]
                        continue

                    qno_match = QUESTION_ANCHOR_RE.match(line_text)
                    if qno_match:
                        qno = int(qno_match.group(1) or qno_match.group(2))
                        baseline = anchor_x_thresholds.get((ref["page"], ref["column"]))
                        if qno > 100 or (baseline is not None and abs(ref["bbox"].x0 - baseline) > 20.0):
                            if current_question is not None:
                                current_question["end_page"] = ref["page"]
                                current_question["end_column"] = ref["column"]
                                current_question["blocks"].append(line_text)
                                current_question["block_refs"].append(
                                    {"page": ref["page"], "column": ref["column"], "bbox": ref["bbox"]}
                                )
                            continue
                        flush_current()
                        current_question = {
                            "question_no": qno,
                            "subject": current_subject,
                            "start_page": ref["page"],
                            "end_page": ref["page"],
                            "start_column": ref["column"],
                            "end_column": ref["column"],
                            "blocks": [_strip_question_number(line_text)],
                            "block_refs": [{"page": ref["page"], "column": ref["column"], "bbox": ref["bbox"]}],
                        }
                        continue

                    if current_question is None:
                        continue

                    current_question["end_page"] = ref["page"]
                    current_question["end_column"] = ref["column"]
                    current_question["blocks"].append(line_text)
                    current_question["block_refs"].append(
                        {"page": ref["page"], "column": ref["column"], "bbox": ref["bbox"]}
                    )

            flush_current()

            return {
                "exam": {
                    "title": title,
                    "source_file": str(source),
                    "page_count": len(doc),
                },
                "questions": [_question_to_dict(question) for question in questions],
                "answers": answers,
                "metadata": {
                    "total_questions": len(questions),
                    "answer_count": len(answers),
                },
            }
        finally:
            doc.close()


def parse_exam_pdf(
    pdf_path: Path | str,
    *,
    out_dir: Path | str | None = None,
    dpi: int = 150,
) -> dict[str, Any]:
    return ExamPDFPipeline().run(pdf_path, out_dir=out_dir, dpi=dpi)
