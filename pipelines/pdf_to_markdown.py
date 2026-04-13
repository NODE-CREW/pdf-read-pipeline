#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PDF to Markdown 변환 파이프라인

opendataloader-pdf를 활용하여 PDF를 Markdown으로 변환합니다.
- 텍스트: 마크다운으로 표현
- 그림/표/수식: 이미지로 추출 후 마크다운에 이미지 경로 삽입
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, List, Optional, Tuple

import fitz  # PyMuPDF
from PIL import Image

# 이미지로 추출해야 하는 요소 타입
IMAGE_TARGET_TYPES = {"table", "picture", "image", "formula", "figure"}

# 문항 시작 패턴 (기존 base.py 재사용)
QUESTION_START_RE = re.compile(r"^\s*(\d{1,3})\s*[\.\)]\s*")
CHOICE_LINE_RE = re.compile(
    r"""
    ^\s*
    (?:
        [①②③④⑤⑥⑦⑧⑨⑩]|
        \(\s*[1-5]\s*\)|
        [1-5]\s*[\.\)]
    )
    """,
    re.VERBOSE,
)

# 텍스트로 변환할 요소 타입
TEXT_ELEMENT_TYPES = {"heading", "paragraph", "list", "list item", "text block", "caption"}


@dataclass
class ConversionResult:
    """변환 결과"""
    markdown_path: Path
    images_dir: Path
    metadata_path: Path
    image_count: int = 0
    element_count: int = 0
    questions_dir: Optional[Path] = None
    question_count: int = 0


@dataclass
class Question:
    """문항 정보"""
    qno: int
    content: str
    elements: List[dict] = field(default_factory=list)


@dataclass
class ElementInfo:
    """요소 정보"""
    type: str
    id: int
    page_number: int
    bounding_box: List[float]
    content: str = ""
    heading_level: int = 1
    source: str = ""
    image_path: str = ""
    kids: List["ElementInfo"] = field(default_factory=list)


def filter_image_elements(elements: List[dict]) -> List[dict]:
    """JSON 요소에서 이미지 대상 필터링
    
    Args:
        elements: JSON 요소 리스트
        
    Returns:
        table, picture, image, formula 타입 요소 리스트
    """
    result = []
    
    def traverse(obj: Any) -> None:
        if isinstance(obj, dict):
            elem_type = obj.get("type", "")
            if elem_type in IMAGE_TARGET_TYPES:
                result.append(obj)
            # 중첩 요소 탐색
            for key in ("kids", "list items"):
                if key in obj:
                    traverse(obj[key])
        elif isinstance(obj, list):
            for item in obj:
                traverse(item)
    
    traverse(elements)
    return result


def generate_image_filename(elem_type: str, page: int, index: int) -> str:
    """이미지 파일명 생성
    
    규칙: <type>_p<page>_<index>.png
    예: table_p01_001.png, figure_p02_003.png
    
    Args:
        elem_type: 요소 타입 (table, figure, formula 등)
        page: 페이지 번호 (1-indexed)
        index: 인덱스 번호 (1-indexed)
        
    Returns:
        파일명 문자열
    """
    # 타입 정규화
    type_map = {
        "picture": "figure",
        "image": "figure",
    }
    normalized_type = type_map.get(elem_type, elem_type)
    return f"{normalized_type}_p{page:02d}_{index:03d}.png"


def crop_image_from_bbox(
    pdf_doc: fitz.Document,
    page_number: int,
    bbox: List[float],
    dpi: int = 150,
) -> Optional[Image.Image]:
    """bounding box 기반 이미지 crop
    
    Args:
        pdf_doc: PyMuPDF 문서 객체
        page_number: 페이지 번호 (1-indexed)
        bbox: bounding box [left, bottom, right, top]
        dpi: 해상도
        
    Returns:
        PIL Image 또는 None
    """
    if not bbox or len(bbox) < 4:
        return None
    
    try:
        page = pdf_doc[page_number - 1]
        page_height = page.rect.height
        
        # opendataloader bbox: [left, bottom, right, top] (PDF 좌표계)
        # PyMuPDF rect: [x0, y0, x1, y1] (상단 좌표계)
        left, bottom, right, top = bbox
        
        # PDF 좌표계 → PyMuPDF 좌표계 변환
        x0 = left
        y0 = page_height - top
        x1 = right
        y1 = page_height - bottom
        
        # 클리핑 영역 설정
        clip_rect = fitz.Rect(x0, y0, x1, y1)
        
        # 확대 행렬 계산
        zoom = dpi / 72.0
        mat = fitz.Matrix(zoom, zoom)
        
        # 이미지 렌더링
        pix = page.get_pixmap(matrix=mat, clip=clip_rect)
        
        # PIL Image로 변환
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        return img
        
    except Exception:
        return None


def element_to_markdown(element: dict, images_rel_path: str = "./images") -> str:
    """요소를 마크다운으로 변환
    
    Args:
        element: JSON 요소
        images_rel_path: 이미지 상대 경로
        
    Returns:
        마크다운 문자열
    """
    elem_type = element.get("type", "")
    content = element.get("content", "")
    
    # 헤딩
    if elem_type == "heading":
        level = element.get("heading level", 1)
        level = min(max(level, 1), 6)  # 1-6 범위 제한
        return f"{'#' * level} {content}"
    
    # 문단
    if elem_type in ("paragraph", "text block"):
        return content
    
    # 캡션
    if elem_type == "caption":
        return f"*{content}*"
    
    # 리스트
    if elem_type == "list":
        items = element.get("list items", [])
        lines = []
        for item in items:
            item_content = item.get("content", "")
            lines.append(f"- {item_content}")
            # 중첩 요소 처리
            for kid in item.get("kids", []):
                kid_md = element_to_markdown(kid, images_rel_path)
                if kid_md:
                    lines.append(f"  {kid_md}")
        return "\n".join(lines)
    
    # 리스트 아이템
    if elem_type == "list item":
        return f"- {content}"
    
    # 테이블 (이미지로 처리)
    if elem_type == "table":
        image_path = element.get("_image_path", "")
        if image_path:
            return f"![표]({image_path})"
        return ""
    
    # 이미지/그림
    if elem_type in ("image", "picture", "figure"):
        image_path = element.get("_image_path", "")
        if not image_path:
            # opendataloader가 추출한 이미지 경로 사용
            source = element.get("source", "")
            if source:
                image_path = f"{images_rel_path}/{Path(source).name}"
        if image_path:
            return f"![그림]({image_path})"
        return ""
    
    # 수식
    if elem_type == "formula":
        # LaTeX 있으면 inline 사용, 없으면 이미지
        latex = element.get("latex", "")
        if latex:
            return f"${latex}$"
        image_path = element.get("_image_path", "")
        if image_path:
            return f"![수식]({image_path})"
        return ""
    
    return ""


def traverse_elements(data: dict) -> Iterator[dict]:
    """JSON 데이터에서 최상위 요소만 순회 (중첩 요소는 element_to_markdown에서 처리)
    
    Args:
        data: JSON 데이터
        
    Yields:
        각 최상위 요소 딕셔너리
    """
    # 중첩 요소(kids, list items)는 부모 요소에서 처리하므로
    # 여기서는 kids 배열의 직접 자식만 순회
    for child in data.get("kids", []):
        if isinstance(child, dict) and "type" in child:
            elem_type = child.get("type", "")
            # header/footer 내부 요소는 별도 처리
            if elem_type in ("header", "footer"):
                for sub in child.get("kids", []):
                    if isinstance(sub, dict) and "type" in sub:
                        yield sub
            else:
                yield child


def assemble_markdown(
    elements: List[dict],
    images_rel_path: str = "./images",
) -> str:
    """마크다운 문서 조립
    
    Args:
        elements: JSON 요소 리스트
        images_rel_path: 이미지 상대 경로
        
    Returns:
        완성된 마크다운 문자열
    """
    lines = []
    prev_type = ""
    
    for element in elements:
        elem_type = element.get("type", "")
        md = element_to_markdown(element, images_rel_path)
        
        if not md:
            continue
        
        # 헤딩/리스트 앞에 빈 줄 추가
        if elem_type in ("heading", "list") and prev_type and prev_type not in ("heading",):
            lines.append("")
        
        # 문단 사이 빈 줄
        if elem_type in ("paragraph", "text block") and prev_type in ("paragraph", "text block"):
            lines.append("")
        
        lines.append(md)
        prev_type = elem_type
    
    return "\n".join(lines)


def split_into_questions(markdown_content: str) -> List[Question]:
    """마크다운 내용을 문항별로 분리
    
    Args:
        markdown_content: 전체 마크다운 문자열
        
    Returns:
        Question 리스트
    """
    lines = markdown_content.split("\n")
    questions: List[Question] = []
    current_qno: Optional[int] = None
    current_lines: List[str] = []
    
    for line in lines:
        # 문항 시작 패턴 검사
        match = QUESTION_START_RE.match(line.lstrip("- "))
        if match:
            # 이전 문항 저장
            if current_qno is not None and current_lines:
                questions.append(Question(
                    qno=current_qno,
                    content="\n".join(current_lines).strip(),
                ))
            
            current_qno = int(match.group(1))
            current_lines = [line]
        elif current_qno is not None:
            current_lines.append(line)
    
    # 마지막 문항 저장
    if current_qno is not None and current_lines:
        questions.append(Question(
            qno=current_qno,
            content="\n".join(current_lines).strip(),
        ))
    
    return questions


def save_questions_separately(
    questions: List[Question],
    questions_dir: Path,
    images_rel_path: str = "../images",
) -> int:
    """문항별로 별도 파일 저장
    
    Args:
        questions: Question 리스트
        questions_dir: 저장 디렉토리
        images_rel_path: 이미지 상대 경로
        
    Returns:
        저장된 문항 수
    """
    questions_dir.mkdir(parents=True, exist_ok=True)
    
    for q in questions:
        # 이미지 경로 조정 (./images → ../images)
        content = q.content.replace("./images/", f"{images_rel_path}/")
        
        filename = f"q{q.qno:03d}.md"
        filepath = questions_dir / filename
        
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"# 문제 {q.qno}\n\n")
            f.write(content)
    
    return len(questions)


def convert_pdf_to_markdown(
    pdf_path: Path,
    output_dir: Path,
    *,
    use_opendataloader: bool = True,
    dpi: int = 150,
) -> ConversionResult:
    """PDF를 Markdown으로 변환
    
    Args:
        pdf_path: PDF 파일 경로
        output_dir: 출력 디렉토리
        use_opendataloader: opendataloader-pdf 사용 여부
        dpi: 이미지 해상도
        
    Returns:
        ConversionResult
    """
    pdf_path = Path(pdf_path)
    output_dir = Path(output_dir)
    pdf_name = pdf_path.stem
    
    # 출력 디렉토리 구조 생성
    doc_dir = output_dir / pdf_name
    images_dir = doc_dir / "images"
    raw_json_dir = doc_dir / "raw_json"
    
    doc_dir.mkdir(parents=True, exist_ok=True)
    images_dir.mkdir(exist_ok=True)
    raw_json_dir.mkdir(exist_ok=True)
    
    # opendataloader-pdf로 파싱
    if use_opendataloader:
        import opendataloader_pdf
        
        opendataloader_pdf.convert(
            input_path=[str(pdf_path)],
            output_dir=str(raw_json_dir),
            format="json",
        )
        
        json_path = raw_json_dir / f"{pdf_name}.json"
    else:
        # 기존 JSON 사용
        json_path = raw_json_dir / f"{pdf_name}.json"
        if not json_path.exists():
            raise FileNotFoundError(f"JSON 파일을 찾을 수 없습니다: {json_path}")
    
    # JSON 로드
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)
    
    # opendataloader가 추출한 이미지 복사
    odl_images_dir = raw_json_dir / f"{pdf_name}_images"
    if odl_images_dir.exists():
        for img_file in odl_images_dir.glob("*.png"):
            shutil.copy(img_file, images_dir / img_file.name)
    
    # 이미지 요소 처리 (추가 crop 필요시)
    pdf_doc = fitz.open(pdf_path)
    image_elements = filter_image_elements(data.get("kids", []))
    
    page_counters: dict[int, dict[str, int]] = {}
    
    for elem in image_elements:
        page_num = elem.get("page number", 1)
        elem_type = elem.get("type", "unknown")
        bbox = elem.get("bounding box")
        
        # 이미 source가 있으면 (opendataloader가 추출) 경로만 설정
        if elem.get("source"):
            source_name = Path(elem["source"]).name
            elem["_image_path"] = f"./images/{source_name}"
            continue
        
        # bounding box가 있으면 crop
        if bbox:
            if page_num not in page_counters:
                page_counters[page_num] = {}
            if elem_type not in page_counters[page_num]:
                page_counters[page_num][elem_type] = 0
            page_counters[page_num][elem_type] += 1
            
            index = page_counters[page_num][elem_type]
            filename = generate_image_filename(elem_type, page_num, index)
            
            img = crop_image_from_bbox(pdf_doc, page_num, bbox, dpi=dpi)
            if img:
                img.save(images_dir / filename)
                elem["_image_path"] = f"./images/{filename}"
    
    pdf_doc.close()
    
    # 마크다운 조립
    all_elements = list(traverse_elements(data))
    markdown_content = assemble_markdown(all_elements)
    
    # 파일 저장
    markdown_path = doc_dir / "document.md"
    with open(markdown_path, "w", encoding="utf-8") as f:
        f.write(markdown_content)
    
    # 문항별 분리 저장
    questions_dir = doc_dir / "questions"
    questions = split_into_questions(markdown_content)
    question_count = save_questions_separately(questions, questions_dir)
    
    # 메타데이터 저장
    metadata = {
        "source_pdf": str(pdf_path),
        "number_of_pages": data.get("number of pages", 0),
        "author": data.get("author"),
        "title": data.get("title"),
        "creation_date": data.get("creation date"),
        "element_count": len(all_elements),
        "image_count": len(list(images_dir.glob("*.png"))),
        "question_count": question_count,
    }
    
    metadata_path = doc_dir / "metadata.json"
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)
    
    return ConversionResult(
        markdown_path=markdown_path,
        images_dir=images_dir,
        metadata_path=metadata_path,
        image_count=metadata["image_count"],
        element_count=metadata["element_count"],
        questions_dir=questions_dir,
        question_count=question_count,
    )


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="PDF to Markdown 변환")
    parser.add_argument("pdf", type=Path, help="입력 PDF 파일")
    parser.add_argument(
        "-o", "--output-dir",
        type=Path,
        default=Path("./output"),
        help="출력 디렉토리 (기본: ./output)",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=150,
        help="이미지 해상도 (기본: 150)",
    )
    
    args = parser.parse_args()
    
    result = convert_pdf_to_markdown(
        args.pdf,
        args.output_dir,
        dpi=args.dpi,
    )
    
    print(f"변환 완료:")
    print(f"  마크다운: {result.markdown_path}")
    print(f"  이미지: {result.images_dir} ({result.image_count}개)")
    print(f"  메타데이터: {result.metadata_path}")
