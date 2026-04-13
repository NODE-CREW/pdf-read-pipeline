#!/usr/bin/env python3
"""
JSON(opendataloader-pdf-hybrid 등)에서 type이 "image"인 노드를 모두 찾아
page number 페이지의 bounding box 영역을 잘라 PNG로 저장합니다.

기본(--bbox-coords pdf)은 PDF 사용자 좌표계(ISO 32000): 원점 **페이지 좌하단**,
x는 오른쪽, y는 **위**가 양수. 값은 [x_min, y_min, x_max, y_max]이며
y_min이 사각형 **아래**(페이지에서 낮은 y), y_max가 **위**(높은 y).

PyMuPDF는 원점이 **좌상단**이고 y는 아래로 증가하므로, pdf 모드에서 내부적으로
y' = page_height - y 변환을 합니다. 예전 스크립트는 이 변환 없이 잘라 같은 크기지만
**위아래가 다른 영역**이 나올 수 있었습니다.

--bbox-coords topleft 는 [left, top, right, bottom] (좌상단 원점·y 아래)로
PyMuPDF clip과 동일하게 취급합니다.

화질·해상도:
  PDF에 “문서 전체 DPI”처럼 쓸 만한 단일 값은 대개 없습니다. 이 스크립트는
  **페이지를 다시 래스터화**한 뒤 clip 하므로, 임베디드 비트맵을 디코드만 해서
  쓰는 것과는 다릅니다.

  --dpi auto: **clip 영역과 겹치는 임베디드 이미지**의 픽셀/표시 크기로 유효 dpi를
  추정해 노드마다 렌더합니다. 비트맵이 없으면 --fallback-dpi(기본 300)를 씁니다.
  순수 벡터 도표는 추정이 안 되어 fallback으로 갑니다.

사용 예:
  python crop_json_image_regions.py \\
    --json output/comh1_040215.json \\
    --pdf 컴활문제/01_raw/comh1_040215.pdf \\
    --out-dir output/comh1_040215_crops \\
    --dpi auto
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Iterator

DpiMode = float | str  # float = 고정 dpi, "auto"

try:
    import fitz  # PyMuPDF
except ImportError as e:  # pragma: no cover
    raise SystemExit(
        "PyMuPDF 패키지가 필요합니다. 설치: pip install pymupdf"
    ) from e


def iter_image_nodes(obj: Any) -> Iterator[dict[str, Any]]:
    """kids / list items 를 재귀적으로 순회하며 image 노드만 내보냅니다."""
    if isinstance(obj, dict):
        if obj.get("type") == "image":
            yield obj
        for key in ("kids", "list items"):
            child = obj.get(key)
            if isinstance(child, list):
                for item in child:
                    yield from iter_image_nodes(item)
    elif isinstance(obj, list):
        for item in obj:
            yield from iter_image_nodes(item)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_pdf(json_path: Path, data: dict[str, Any], pdf_arg: Path | None) -> Path:
    if pdf_arg is not None:
        p = pdf_arg.expanduser().resolve()
        if not p.is_file():
            raise FileNotFoundError(f"PDF 없음: {p}")
        return p
    name = data.get("file name")
    if not name:
        raise ValueError('JSON에 "file name" 키가 없고 --pdf 도 지정되지 않았습니다.')
    candidate = (json_path.parent / name).resolve()
    if not candidate.is_file():
        raise FileNotFoundError(
            f"PDF를 찾을 수 없습니다: {candidate}\n"
            f"  --pdf 로 원본 PDF 경로를 직접 지정하세요."
        )
    return candidate


def bbox_to_clip_rect(
    page: fitz.Page, x0: float, y0: float, x1: float, y1: float, coords: str
) -> fitz.Rect:
    """JSON bbox를 PyMuPDF clip Rect로 변환."""
    if coords == "topleft":
        return fitz.Rect(x0, y0, x1, y1)
    if coords == "pdf":
        # PDF user space: origin bottom-left, y increases upward.
        # bbox: [x_min, y_min, y_max] at bottom, y_max at top (y_min < y_max).
        h = float(page.rect.height)
        return fitz.Rect(x0, h - y1, x1, h - y0)
    raise ValueError(f"알 수 없는 --bbox-coords: {coords}")


def estimate_dpi_from_embedded_images(
    page: fitz.Page,
    clip_rect: fitz.Rect,
    *,
    dpi_max: float,
    dpi_min: float = 72.0,
) -> float | None:
    """
    clip_rect와 교차하는 임베디드 이미지마다
    dpi ≈ 72 * (픽셀 크기) / (페이지에 그려진 변 길이, pt) 로 추정하고
    그 중 최댓값을 사용합니다. 교차 이미지가 없으면 None.
    """
    doc = page.parent
    best = 0.0
    for item in page.get_images(full=True):
        xref = item[0]
        try:
            rects = page.get_image_rects(xref)
        except Exception:
            continue
        try:
            info = doc.extract_image(xref)
        except Exception:
            continue
        pw = int(info.get("width") or 0)
        ph = int(info.get("height") or 0)
        if pw < 1 or ph < 1:
            continue
        for r in rects:
            if r.is_empty or r.width <= 0 or r.height <= 0:
                continue
            inter = r & clip_rect
            if inter.is_empty or inter.get_area() <= 0:
                continue
            dpi_x = 72.0 * pw / r.width
            dpi_y = 72.0 * ph / r.height
            d = max(dpi_x, dpi_y)
            if d > best:
                best = d
    if best <= 0:
        return None
    d = max(dpi_min, min(float(math.ceil(best)), dpi_max))
    return int(round(d))


def parse_dpi_option(s: str) -> DpiMode:
    t = s.strip().lower()
    if t == "auto":
        return "auto"
    return float(s)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="JSON의 image 노드 bbox를 PDF에서 잘라 PNG 저장"
    )
    parser.add_argument(
        "--json",
        type=Path,
        required=True,
        help="파싱 결과 JSON 경로 (예: output/comh1_040215.json)",
    )
    parser.add_argument(
        "--pdf",
        type=Path,
        default=None,
        help="원본 PDF 경로 (미지정 시 JSON과 같은 디렉터리의 file name 필드 사용)",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        required=True,
        help="크롭 PNG를 둘 디렉터리 (없으면 생성)",
    )
    parser.add_argument(
        "--zoom",
        type=float,
        default=2.0,
        help="렌더 배율 (72pt 기준; 기본 2). --dpi 를 주면(숫자 또는 auto) 무시됩니다.",
    )
    parser.add_argument(
        "--dpi",
        type=parse_dpi_option,
        default=None,
        metavar="N|auto",
        help=(
            "렌더 dpi. 숫자: 고정 해상도. auto: clip과 겹치는 임베디드 이미지에서 "
            "유효 dpi 추정(노드별). 미지정 시 --zoom 사용."
        ),
    )
    parser.add_argument(
        "--fallback-dpi",
        type=float,
        default=300.0,
        help="--dpi auto 인데 clip 안에 임베디드 비트맵이 없을 때 쓸 dpi (기본 300)",
    )
    parser.add_argument(
        "--dpi-max",
        type=float,
        default=600.0,
        help="auto 추정 상한(기본 600). 메모리 폭주 방지.",
    )
    parser.add_argument(
        "--prefix",
        default="crop",
        help="저장 파일명 접두사 (기본 crop)",
    )
    parser.add_argument(
        "--bbox-coords",
        choices=("pdf", "topleft"),
        default="pdf",
        help=(
            "pdf: ISO PDF 사용자 공간(좌하단 원점, [x0,y0,x1,y1]의 "
            "y는 아래쪽이 작음). topleft: PyMuPDF와 동일 [left,top,right,bottom]."
        ),
    )
    args = parser.parse_args()

    json_path = args.json.expanduser().resolve()
    data = load_json(json_path)
    pdf_path = resolve_pdf(json_path, data, args.pdf)
    out_dir = args.out_dir.expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    stem = json_path.stem

    doc = fitz.open(pdf_path)
    try:
        n_pages = len(doc)
        for idx, node in enumerate(iter_image_nodes(data.get("kids", []))):
            page_no = int(node["page number"])
            if page_no < 1 or page_no > n_pages:
                raise ValueError(
                    f"image id={node.get('id')}: page number {page_no} 가 "
                    f"PDF 페이지 수({n_pages}) 범위를 벗어났습니다."
                )
            box = node["bounding box"]
            if len(box) != 4:
                raise ValueError(f"bounding box 길이는 4여야 합니다: {box}")
            x0, y0, x1, y1 = (float(box[0]), float(box[1]), float(box[2]), float(box[3]))
            page = doc[page_no - 1]
            rect = bbox_to_clip_rect(page, x0, y0, x1, y1, args.bbox_coords)

            dpi_note = ""
            if args.dpi == "auto":
                est = estimate_dpi_from_embedded_images(
                    page, rect, dpi_max=args.dpi_max
                )
                dpi_use = est if est is not None else int(round(args.fallback_dpi))
                dpi_note = (
                    f" dpi={dpi_use}(auto"
                    + (f", est={est}" if est is not None else ", fallback")
                    + ")"
                )
                pix = page.get_pixmap(dpi=dpi_use, clip=rect, alpha=False)
            elif args.dpi is not None:
                dpi_fixed = int(round(float(args.dpi)))
                dpi_note = f" dpi={dpi_fixed}"
                pix = page.get_pixmap(dpi=dpi_fixed, clip=rect, alpha=False)
            else:
                mat = fitz.Matrix(args.zoom, args.zoom)
                pix = page.get_pixmap(matrix=mat, clip=rect, alpha=False)
                dpi_note = f" zoom={args.zoom}"

            id_part = node.get("id")
            if id_part is not None:
                fname = f"{args.prefix}_{stem}_id{id_part:04d}_p{page_no}.png"
            else:
                fname = f"{args.prefix}_{stem}_n{idx:04d}_p{page_no}.png"

            out_path = out_dir / fname
            pix.save(out_path.as_posix())
            src = node.get("source", "")
            print(
                f"wrote {out_path.name}  ({pix.width}x{pix.height}){dpi_note}  source={src}"
            )
    finally:
        doc.close()


if __name__ == "__main__":
    main()
