#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import importlib
import json
import shutil
from pathlib import Path

from pipelines.question_parser import parse_pdf_json


def build_output_path(pdf_path: Path, output_dir: Path) -> Path:
    return output_dir / f"{pdf_path.stem}_questions.json"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="시험지형 PDF를 Phase 1 구조화 JSON으로 변환합니다.",
    )
    parser.add_argument(
        "pdf",
        nargs="+",
        help="입력 PDF 파일 경로 (여러 개 가능)",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        default="output/exam_pdf",
        help="결과 JSON 저장 디렉토리 (기본값: output/exam_pdf)",
    )
    parser.add_argument(
        "--indent",
        type=int,
        default=2,
        help="JSON 들여쓰기 크기 (기본값: 2)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for pdf_arg in args.pdf:
        pdf_path = Path(pdf_arg).expanduser().resolve()
        if not pdf_path.is_file():
            raise FileNotFoundError(f"PDF 파일을 찾을 수 없습니다: {pdf_path}")

        temp_json_dir = output_dir / "_temp_json"
        temp_json_dir.mkdir(parents=True, exist_ok=True)

        try:
            try:
                opendataloader_pdf = importlib.import_module("opendataloader_pdf")
            except ImportError as exc:
                raise ImportError(
                    "opendataloader-pdf가 설치되지 않았습니다.\n"
                    "pip install opendataloader-pdf"
                ) from exc

            opendataloader_pdf.convert(
                input_path=[str(pdf_path)],
                output_dir=str(temp_json_dir),
                format="json",
            )

            json_path = temp_json_dir / f"{pdf_path.stem}.json"
            if not json_path.is_file():
                raise FileNotFoundError(f"opendataloader JSON을 찾을 수 없습니다: {json_path}")

            result = parse_pdf_json(
                json_path,
                pdf_path=pdf_path,
                out_dir=output_dir,
                dpi=150,
            )
        finally:
            if temp_json_dir.exists():
                shutil.rmtree(temp_json_dir)

        out_path = build_output_path(pdf_path, output_dir)
        out_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=args.indent) + "\n",
            encoding="utf-8",
        )
        print(
            f"[saved] {pdf_path} -> {out_path} "
            f"(questions={result['metadata']['total_questions']}, image_crops={len(result['image_crops'])})"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
