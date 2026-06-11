#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""opendataloader JSON에서 문제별 구조화 JSON을 추출하는 final 파서 보조 모듈."""

import argparse
import sys
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
_project_root = Path(__file__).resolve().parents[2]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from pipelines.question_parser import parse_pdf_json


def parse_questions_from_pdf(pdf_path: Path, out_dir: Path, dpi: int = 150) -> dict:
    """PDF를 opendataloader JSON으로 변환한 뒤 문제 구조 JSON으로 파싱한다."""
    pdf_path = pdf_path.expanduser().resolve()
    out_dir = out_dir.expanduser().resolve()
    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF 파일을 찾을 수 없습니다: {pdf_path}")

    temp_json_dir = out_dir / "_temp_json"
    temp_json_dir.mkdir(parents=True, exist_ok=True)
    try:
        try:
            import opendataloader_pdf
            opendataloader_pdf.convert(
                input_path=[str(pdf_path)],
                output_dir=str(temp_json_dir),
                format="json",
            )
        except ImportError as exc:
            raise ImportError(
                "opendataloader-pdf가 설치되지 않았습니다.\n"
                "pip install opendataloader-pdf"
            ) from exc

        json_path = temp_json_dir / f"{pdf_path.stem}.json"
        if not json_path.is_file():
            raise FileNotFoundError(
                f"opendataloader-pdf가 JSON을 생성하지 못했습니다: {json_path}"
            )
        return parse_pdf_json(json_path, pdf_path=pdf_path, out_dir=out_dir, dpi=dpi)
    finally:
        if temp_json_dir.exists():
            import shutil

            shutil.rmtree(temp_json_dir)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="PDF 또는 opendataloader JSON에서 문제별 구조화 JSON 추출"
    )
    parser.add_argument(
        "--json",
        type=Path,
        default=None,
        help="opendataloader JSON 파일 경로 (선택, 생략 시 --pdf 필수)",
    )
    parser.add_argument(
        "--pdf",
        type=Path,
        default=None,
        help="원본 PDF 경로 (--json 생략 시 필수, 있으면 이미지 crop도 수행)",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        required=True,
        help="출력 디렉토리",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=150,
        help="이미지 crop 해상도 (기본 150)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    # --json과 --pdf 중 최소 하나는 필수
    if not args.json and not args.pdf:
        raise ValueError("--json 또는 --pdf 중 하나는 반드시 지정해야 합니다.")

    out_dir = args.out_dir.expanduser().resolve()

    # JSON 경로 확정
    json_path: Path
    temp_json_dir: Path | None = None

    if args.json:
        # 기존 방식: JSON 파일이 지정된 경우
        json_path = args.json.expanduser().resolve()
        if not json_path.is_file():
            raise FileNotFoundError(f"JSON 파일을 찾을 수 없습니다: {json_path}")
    else:
        # 신규 방식: PDF만 지정된 경우 → opendataloader로 JSON 생성
        if not args.pdf:
            raise ValueError("--json을 생략하면 --pdf는 필수입니다.")
        
        pdf_path_for_convert = args.pdf.expanduser().resolve()
        if not pdf_path_for_convert.is_file():
            raise FileNotFoundError(f"PDF 파일을 찾을 수 없습니다: {pdf_path_for_convert}")

        # 임시 디렉토리에 JSON 생성
        temp_json_dir = out_dir / "_temp_json"
        temp_json_dir.mkdir(parents=True, exist_ok=True)

        print(f"[단계 1/2] opendataloader-pdf로 JSON 생성 중...")
        try:
            import opendataloader_pdf
            opendataloader_pdf.convert(
                input_path=[str(pdf_path_for_convert)],
                output_dir=str(temp_json_dir),
                format="json",
            )
        except ImportError:
            raise ImportError(
                "opendataloader-pdf가 설치되지 않았습니다.\n"
                "pip install opendataloader-pdf"
            )

        json_path = temp_json_dir / f"{pdf_path_for_convert.stem}.json"
        if not json_path.is_file():
            raise FileNotFoundError(
                f"opendataloader-pdf가 JSON을 생성하지 못했습니다: {json_path}"
            )
        print(f"  → JSON 생성 완료: {json_path}")

    # PDF 경로 확정
    pdf_path = None
    if args.pdf:
        pdf_path = args.pdf.expanduser().resolve()
        if not pdf_path.is_file():
            raise FileNotFoundError(f"PDF 파일을 찾을 수 없습니다: {pdf_path}")

    # 파싱 실행
    print(f"[단계 2/2] 문제 추출 중...")
    result = parse_pdf_json(
        json_path,
        pdf_path=pdf_path,
        out_dir=out_dir,
        dpi=args.dpi,
    )

    # 임시 JSON 디렉토리 정리
    if temp_json_dir and temp_json_dir.exists():
        import shutil
        shutil.rmtree(temp_json_dir)
        print(f"  → 임시 JSON 정리됨")

    meta = result["metadata"]
    print(f"[완료] {result['source']}")
    print(f"  - 문제 수: {meta['total_questions']}")
    print(f"  - 페이지 수: {meta['pages']}")
    print(f"  - 필터링된 노드: {meta['filtered_nodes']}")
    print(f"  - 이미지 crop: {len(result['image_crops'])}개")
    print(f"  - 출력: {out_dir / (json_path.stem + '_questions.json')}")


if __name__ == "__main__":
    main()
