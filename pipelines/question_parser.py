#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
opendataloader JSON에서 문제별 구조화 JSON을 추출하는 파서.

- 텍스트 기반 PDF만 처리 (OCR 없음)
- header/footer/caption 노드 제거
- list item content에서 문제 번호 패턴 감지
- 하위 kids에서 선택지(①②③④) 파싱
- image/table 요소는 bounding box 기반 crop 대상으로 수집
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterator

# 문제 번호 패턴: "1.", "1)", "1 " (숫자 뒤 마침표·괄호·공백)
QUESTION_NUMBER_RE = re.compile(r"^\s*(\d{1,3})\s*[\.\)]\s*|^\s*(\d{1,3})\s+(?!\d)")

# 원문자 선택지 패턴
CIRCLED_NUMBERS = "①②③④⑤⑥⑦⑧⑨⑩"
CHOICE_MARKER_RE = re.compile(r"[①②③④⑤⑥⑦⑧⑨⑩]")
CHOICE_SPLIT_RE = re.compile(r"(?=[①②③④⑤⑥⑦⑧⑨⑩])")

# 이미지로 crop해야 하는 요소 타입
IMAGE_TARGET_TYPES = {"image", "table", "picture", "figure", "formula"}

# 필터링 대상 노드 타입
FILTERED_NODE_TYPES = {"header", "footer", "caption"}


def _circled_to_number(marker: str) -> int:
    """① → 1, ② → 2, ..."""
    idx = CIRCLED_NUMBERS.find(marker)
    return idx + 1 if idx >= 0 else 0


def _extract_question_number(content: str) -> int | None:
    """content 문자열에서 문제 번호를 추출. 매칭 실패 시 None."""
    m = QUESTION_NUMBER_RE.match(content)
    if not m:
        return None
    return int(m.group(1) or m.group(2))


def _strip_question_number(content: str) -> str:
    """content에서 문제 번호 부분을 제거한 본문 텍스트 반환."""
    m = QUESTION_NUMBER_RE.match(content)
    if not m:
        return content.strip()
    return content[m.end():].strip()


# ──────────────────────────────────────────────
# 노드 필터링
# ──────────────────────────────────────────────

def filter_content_nodes(kids: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """header, footer, caption 노드를 제거하고 본문 노드만 반환.

    단, 선택지 마커(①②...)가 포함된 caption은 유지.
    """
    result: list[dict[str, Any]] = []
    for kid in kids:
        node_type = kid.get("type")
        if node_type in FILTERED_NODE_TYPES:
            if node_type == "caption" and CHOICE_MARKER_RE.search(kid.get("content", "")):
                result.append(kid)
            continue
        result.append(kid)
    return result


# ──────────────────────────────────────────────
# 선택지 파싱
# ──────────────────────────────────────────────

def _parse_choices_from_text(text: str) -> list[dict[str, Any]]:
    """텍스트에서 ①②③④ 마커로 선택지를 분리."""
    parts = CHOICE_SPLIT_RE.split(text)
    choices: list[dict[str, Any]] = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        m = CHOICE_MARKER_RE.match(part)
        if not m:
            continue
        marker = m.group(0)
        number = _circled_to_number(marker)
        choice_text = part[len(marker):].strip()
        choices.append({"number": number, "text": choice_text})
    return choices


def parse_choices_from_kids(kids: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """문제의 kids 노드에서 선택지를 추출.

    두 가지 패턴을 처리:
    1. paragraph 내 텍스트: "① A ② B ③ C ④ D"
    2. 중첩 list (circled arabic numbers): list > list item
    """
    choices: list[dict[str, Any]] = []

    for kid in kids:
        kid_type = kid.get("type", "")

        # 패턴 1: paragraph / text block 내 원문자
        if kid_type in ("paragraph", "text block"):
            content = kid.get("content", "")
            # text block은 kids > paragraph에 content가 있을 수 있음
            if not content and kid.get("kids"):
                for sub in kid["kids"]:
                    if isinstance(sub, dict):
                        content += " " + sub.get("content", "")
                content = content.strip()
            if CHOICE_MARKER_RE.search(content):
                choices.extend(_parse_choices_from_text(content))

        # 패턴 2: 중첩 list (circled arabic numbers)
        elif kid_type == "list":
            items = kid.get("list items", [])
            for idx, item in enumerate(items):
                if not isinstance(item, dict):
                    continue
                item_content = item.get("content", "")
                m = CHOICE_MARKER_RE.match(item_content.strip())
                if m:
                    marker = m.group(0)
                    number = _circled_to_number(marker)
                    choice_text = item_content.strip()[len(marker):].strip()
                else:
                    number = idx + 1
                    choice_text = item_content.strip()
                choices.append({"number": number, "text": choice_text})

    # 중복 제거 (동일 number가 여러 번 들어올 수 있음)
    seen: set[int] = set()
    deduped: list[dict[str, Any]] = []
    for c in choices:
        if c["number"] not in seen:
            seen.add(c["number"])
            deduped.append(c)
    return deduped


# ──────────────────────────────────────────────
# 이미지 요소 수집
# ──────────────────────────────────────────────

def collect_image_elements(kids: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """재귀적으로 순회하며 image/table/picture/formula 노드만 수집."""
    result: list[dict[str, Any]] = []

    def _traverse(obj: Any) -> None:
        if isinstance(obj, dict):
            if obj.get("type") in IMAGE_TARGET_TYPES:
                result.append(obj)
            for key in ("kids", "list items"):
                child = obj.get(key)
                if isinstance(child, list):
                    for item in child:
                        _traverse(item)
        elif isinstance(obj, list):
            for item in obj:
                _traverse(item)

    _traverse(kids)
    return result


# ──────────────────────────────────────────────
# 문제 추출
# ──────────────────────────────────────────────

def _collect_images_from_kids(kids: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """문제 kids에서 image 요소만 추출 (crop 참조용)."""
    images: list[dict[str, Any]] = []
    for kid in kids:
        if not isinstance(kid, dict):
            continue
        kid_type = kid.get("type", "")
        if kid_type in IMAGE_TARGET_TYPES:
            images.append({
                "type": kid_type,
                "element_id": kid.get("id"),
                "page_number": kid.get("page number"),
                "bounding_box": kid.get("bounding box"),
                "source": kid.get("source", ""),
            })
    return images


def _is_choice_label_only(content: str) -> bool:
    """content가 선택지 마커(①②...)와 공백만으로 구성되어 있는지 확인."""
    stripped = content.strip()
    if not stripped:
        return False
    remaining = CHOICE_MARKER_RE.sub("", stripped).strip()
    return len(remaining) == 0 and CHOICE_MARKER_RE.search(stripped) is not None


def _extract_choice_numbers(content: str) -> list[int]:
    """content에서 선택지 번호를 순서대로 추출. '① ②' → [1, 2]"""
    return [_circled_to_number(m.group(0)) for m in CHOICE_MARKER_RE.finditer(content)]


def _extract_description_from_kids(kids: list[dict[str, Any]]) -> str:
    """문제 kids에서 설명 텍스트를 추출 (선택지, 이미지 제외).

    text block 내부의 paragraph나 unordered list의 항목 텍스트를 수집.
    """
    lines: list[str] = []
    for kid in kids:
        if not isinstance(kid, dict):
            continue
        kid_type = kid.get("type", "")
        if kid_type != "text block":
            continue
        for sub in kid.get("kids", []):
            if not isinstance(sub, dict):
                continue
            sub_type = sub.get("type", "")
            sub_content = sub.get("content", "").strip()
            if sub_type == "paragraph" and sub_content and not CHOICE_MARKER_RE.search(sub_content):
                lines.append(sub_content)
            elif sub_type == "list":
                for item in sub.get("list items", []):
                    if isinstance(item, dict):
                        item_content = item.get("content", "").strip()
                        if item_content and not CHOICE_MARKER_RE.search(item_content):
                            lines.append(item_content)
    return "\n".join(lines)


def _extract_questions_from_list(
    list_node: dict[str, Any],
    *,
    pending_choices: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """list 노드에서 문제를 추출.

    Returns:
        (questions, remaining_pending_choices)
        pending_choices: 이전 문제에 아직 선택지가 할당되지 않은 경우
    """
    questions: list[dict[str, Any]] = []
    items = list_node.get("list items", [])

    for item in items:
        if not isinstance(item, dict):
            continue
        content = item.get("content", "")
        qno = _extract_question_number(content)
        if qno is None:
            continue

        kids = item.get("kids", [])
        choices = parse_choices_from_kids(kids)
        images = _collect_images_from_kids(kids)
        description = _extract_description_from_kids(kids)

        questions.append({
            "question_number": qno,
            "page_number": item.get("page number"),
            "question_text": _strip_question_number(content),
            "description": description,
            "choices": choices,
            "images": images,
            "bounding_box": item.get("bounding box"),
        })

    return questions, []


def _find_last_question_without_choices(
    questions: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """선택지가 없는 가장 최근 문제를 반환. 없으면 None."""
    for q in reversed(questions):
        if not q["choices"]:
            return q
    return None


def extract_questions(filtered_kids: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """필터링된 top-level kids에서 모든 문제를 추출.

    선택지가 형제 list 노드에 있는 경우(kids가 빈 문제)도 처리.
    """
    all_questions: list[dict[str, Any]] = []
    pending_choices: list[dict[str, Any]] = []
    pending_images: list[dict[str, Any]] = []

    for node in filtered_kids:
        node_type = node.get("type", "")

        if node_type == "list":
            # pending_images flush
            if pending_images and all_questions:
                all_questions[-1]["images"].extend(pending_images)
                pending_images = []
            # list의 numbering style 확인
            numbering = node.get("numbering style", "")
            items = node.get("list items", [])

            # 원문자 번호 리스트(선택지 전용 list)인지 확인
            is_choice_list = numbering == "circled arabic numbers"

            if is_choice_list and all_questions:
                # 선택지가 없는 가장 최근 문제를 찾아 할당
                target = _find_last_question_without_choices(all_questions)
                if target is not None:
                    choices: list[dict[str, Any]] = []
                    for idx, item in enumerate(items):
                        if not isinstance(item, dict):
                            continue
                        item_content = item.get("content", "")
                        m = CHOICE_MARKER_RE.match(item_content.strip())
                        if m:
                            marker = m.group(0)
                            number = _circled_to_number(marker)
                            choice_text = item_content.strip()[len(marker):].strip()
                        else:
                            number = idx + 1
                            choice_text = item_content.strip()
                        choices.append({"number": number, "text": choice_text})
                    target["choices"] = choices
            else:
                qs, pending_choices = _extract_questions_from_list(
                    node, pending_choices=pending_choices
                )
                all_questions.extend(qs)

        elif node_type in ("image", "picture", "figure", "formula"):
            # 독립 이미지 노드 → pending_images에 추가
            if all_questions:
                pending_images.append({
                    "type": node_type,
                    "element_id": node.get("id"),
                    "page_number": node.get("page number"),
                    "bounding_box": node.get("bounding box"),
                    "source": node.get("source", ""),
                })

        elif node_type in ("paragraph", "caption"):
            content = node.get("content", "")
            if _is_choice_label_only(content) and pending_images and all_questions:
                # 이미지 선택지 패턴: 레이블에 대응하는 이미지를 선택지로 연결
                choice_numbers = _extract_choice_numbers(content)
                n = len(choice_numbers)
                if n <= len(pending_images):
                    choice_imgs = pending_images[-n:]
                    pending_images = pending_images[:-n]
                    choice_imgs.sort(key=lambda img: (img.get("bounding_box") or [0])[0])
                    target = all_questions[-1]
                    for cnum, img in zip(choice_numbers, choice_imgs):
                        target["choices"].append({"number": cnum, "text": "", "image": img})
            elif CHOICE_MARKER_RE.search(content) and all_questions:
                # 과목 구분 paragraph 또는 독립 선택지 paragraph
                target = _find_last_question_without_choices(all_questions)
                if target is None:
                    target = all_questions[-1]
                new_choices = _parse_choices_from_text(content)
                target["choices"].extend(new_choices)

        elif node_type == "text block":
            # 보기 지문 등 — 직전 문제에 연결
            if all_questions:
                kids_list = node.get("kids", [])
                # heading만 있는 text block은 과목 구분이므로 건너뛰기
                dict_kids = [k for k in kids_list if isinstance(k, dict)]
                if dict_kids and all(k.get("type") == "heading" for k in dict_kids):
                    continue
                content = ""
                for sub in kids_list:
                    if isinstance(sub, dict):
                        content += " " + sub.get("content", "")
                content = content.strip()
                if content:
                    prev = all_questions[-1]
                    prev["question_text"] = prev["question_text"] + "\n" + content

        elif node_type == "table":
            # 정답표 등 — 문제 연결 없으면 무시
            if all_questions and not all_questions[-1]["choices"]:
                # 직전 문제에 이미지로 추가
                all_questions[-1]["images"].append({
                    "type": "table",
                    "element_id": node.get("id"),
                    "page_number": node.get("page number"),
                    "bounding_box": node.get("bounding box"),
                    "source": "",
                })

    # 남은 pending_images flush
    if pending_images and all_questions:
        all_questions[-1]["images"].extend(pending_images)

    # 문제 번호 기준 정렬
    all_questions.sort(key=lambda q: q["question_number"])
    return all_questions


def _link_crops_to_questions(
    questions: list[dict[str, Any]],
    image_crops: list[dict[str, Any]],
) -> None:
    """image_crops의 crop_path를 각 question의 images에 element_id 기준으로 연결."""
    if not image_crops:
        return
    crop_map = {c["element_id"]: c["crop_path"] for c in image_crops}
    for q in questions:
        for img in q.get("images", []):
            eid = img.get("element_id")
            if eid in crop_map:
                img["crop_path"] = crop_map[eid]
        for choice in q.get("choices", []):
            img = choice.get("image")
            if img:
                eid = img.get("element_id")
                if eid in crop_map:
                    img["crop_path"] = crop_map[eid]


# ──────────────────────────────────────────────
# 전체 파이프라인
# ──────────────────────────────────────────────

def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_pdf_json(
    json_path: Path,
    *,
    pdf_path: Path | None = None,
    out_dir: Path | None = None,
    dpi: int = 150,
) -> dict[str, Any]:
    """opendataloader JSON을 파싱하여 문제별 구조화 JSON을 생성.

    Args:
        json_path: opendataloader JSON 파일 경로
        pdf_path: 원본 PDF 경로 (이미지 crop용, 선택)
        out_dir: 출력 디렉토리 (None이면 crop 생략)
        dpi: 이미지 crop 해상도

    Returns:
        구조화 JSON dict
    """
    data = load_json(json_path)
    kids = data.get("kids", [])

    # 1. 헤더/푸터/캡션 필터링
    filtered = filter_content_nodes(kids)
    filtered_count = len(kids) - len(filtered)

    # 2. 문제 추출
    questions = extract_questions(filtered)

    # 3. 이미지 요소 수집
    image_elements = collect_image_elements(filtered)

    # 4. 이미지 crop (PDF + out_dir가 있을 때만)
    image_crops: list[dict[str, Any]] = []
    if pdf_path and out_dir:
        image_crops = _crop_image_elements(
            pdf_path=pdf_path,
            out_dir=out_dir,
            image_elements=image_elements,
            dpi=dpi,
        )

    # 5. crop 결과를 문제별 images에 연결
    _link_crops_to_questions(questions, image_crops)

    # 6. 결과 조립
    source_name = data.get("file name", json_path.stem)
    result = {
        "source": source_name,
        "questions": questions,
        "image_crops": image_crops,
        "metadata": {
            "total_questions": len(questions),
            "pages": data.get("number of pages", 0),
            "filtered_nodes": filtered_count,
        },
    }

    # 7. 저장
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{json_path.stem}_questions.json"
        out_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    return result


def _crop_image_elements(
    *,
    pdf_path: Path,
    out_dir: Path,
    image_elements: list[dict[str, Any]],
    dpi: int,
) -> list[dict[str, Any]]:
    """이미지 요소를 PDF에서 bbox 기반 crop.

    crop_json_image_regions.py의 좌표 변환 로직을 재사용.
    """
    try:
        import fitz
    except ImportError:
        return []

    crops_dir = out_dir / "crops"
    crops_dir.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(pdf_path)
    crops: list[dict[str, Any]] = []
    try:
        n_pages = len(doc)
        for idx, elem in enumerate(image_elements):
            page_no = elem.get("page number")
            bbox = elem.get("bounding box")
            if not page_no or not bbox or len(bbox) != 4:
                continue
            if page_no < 1 or page_no > n_pages:
                continue

            page = doc[page_no - 1]
            page_height = float(page.rect.height)

            # PDF 좌표계 → PyMuPDF 좌표계 변환 (좌하단 원점 → 좌상단 원점)
            x0, y0_pdf, x1, y1_pdf = (float(v) for v in bbox)
            clip_rect = fitz.Rect(x0, page_height - y1_pdf, x1, page_height - y0_pdf)

            zoom = dpi / 72.0
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat, clip=clip_rect, alpha=False)

            elem_id = elem.get("id", idx)
            fname = f"crop_id{elem_id:04d}_p{page_no}.png"
            out_path = crops_dir / fname
            pix.save(out_path.as_posix())

            crops.append({
                "element_id": elem_id,
                "page_number": page_no,
                "type": elem.get("type", ""),
                "bounding_box": bbox,
                "crop_path": f"crops/{fname}",
            })
    finally:
        doc.close()

    return crops
