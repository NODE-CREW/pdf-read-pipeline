#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""최종 PDF 파싱 CLI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from final.ai_enricher import create_openai_client, enrich_question
from final.normalizer import normalize_parser_result
from final.schema import build_final_output, validate_final_output


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PDF를 최종 문제 JSON 스키마로 변환")
    parser.add_argument("--pdf", type=Path, required=True, help="입력 PDF 경로")
    parser.add_argument("--output-dir", type=Path, required=True, help="출력 디렉토리")
    parser.add_argument(
        "--parser",
        choices=["auto", "sinagong", "result"],
        default="auto",
        help="사용할 파서",
    )
    parser.add_argument("--dpi", type=int, default=150, help="이미지 crop DPI")
    parser.add_argument("--ai-base-url", default=None, help="OpenAI-compatible endpoint base_url")
    parser.add_argument("--ai-api-key", default="any-string-ok", help="AI endpoint API key")
    parser.add_argument("--ai-timeout", type=float, default=10.0, help="AI 요청 timeout 초")
    parser.add_argument(
        "--ai-max-failures",
        type=int,
        default=3,
        help="AI 보강 실패가 이 횟수에 도달하면 남은 문제 보강을 중단",
    )
    parser.add_argument(
        "--model",
        default="mlx-community/gemma-4-26b-a4b-it-4bit",
        help="AI 보강 모델명",
    )
    parser.add_argument("--max-retries", type=int, default=3, help="AI JSON 응답 재시도 횟수")
    return parser.parse_args(argv)


def run_sinagong_parser(pdf_path: Path, output_dir: Path, dpi: int) -> dict[str, Any]:
    from final.sinagong_pdf_parser import parse_test1_pdf

    return parse_test1_pdf(pdf_path, out_dir=output_dir / "_sinagong_raw", dpi=dpi)


def run_result_parser(pdf_path: Path, output_dir: Path, dpi: int) -> dict[str, Any]:
    from final.result_pdf_parser.extract_questions import parse_questions_from_pdf

    return parse_questions_from_pdf(pdf_path, out_dir=output_dir / "_result_raw", dpi=dpi)


def parse_with_selected_parser(
    *,
    pdf_path: Path,
    output_dir: Path,
    parser_name: str,
    dpi: int,
) -> dict[str, Any]:
    if parser_name == "sinagong":
        return run_sinagong_parser(pdf_path, output_dir, dpi)
    if parser_name == "result":
        return run_result_parser(pdf_path, output_dir, dpi)

    try:
        return run_sinagong_parser(pdf_path, output_dir, dpi)
    except Exception:
        return run_result_parser(pdf_path, output_dir, dpi)


def apply_ai_enrichment(
    *,
    output: dict[str, Any],
    ai_base_url: str | None,
    ai_api_key: str,
    model: str,
    max_retries: int,
    ai_timeout: float = 10.0,
    ai_max_failures: int = 3,
) -> dict[str, Any]:
    if not ai_base_url:
        return output

    client = create_openai_client(base_url=ai_base_url, api_key=ai_api_key, timeout=ai_timeout)
    ai_errors: list[dict[str, str]] = []
    skipped_questions = 0
    for index, question in enumerate(output["questions"]):
        if len(ai_errors) >= max(ai_max_failures, 1):
            skipped_questions = len(output["questions"]) - index
            break
        question_source = question.get("question_source", "")
        try:
            enrich_question(
                client=client,
                model=model,
                question=question,
                max_retries=max_retries,
            )
        except Exception as exc:
            ai_errors.append(
                {
                    "question_source": str(question_source),
                    "error": str(exc),
                }
            )
    output["metadata"]["requires_answer_review"] = any(
        question["options"] and not any(option["is_correct"] for option in question["options"])
        for question in output["questions"]
    ) or bool(ai_errors)
    output["metadata"]["ai_enrichment"] = {
        "enabled": True,
        "failed_questions": len(ai_errors),
        "skipped_questions": skipped_questions,
        "errors": ai_errors[:10],
    }
    validate_final_output(output)
    return output


def run_pipeline(
    *,
    pdf_path: Path,
    output_dir: Path,
    parser_name: str,
    dpi: int,
    ai_base_url: str | None,
    model: str,
    max_retries: int,
    ai_api_key: str = "any-string-ok",
    ai_timeout: float = 10.0,
    ai_max_failures: int = 3,
) -> Path:
    pdf_path = pdf_path.expanduser().resolve()
    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF 파일을 찾을 수 없다: {pdf_path}")

    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    parser_result = parse_with_selected_parser(
        pdf_path=pdf_path,
        output_dir=output_dir,
        parser_name=parser_name,
        dpi=dpi,
    )
    normalized = normalize_parser_result(parser_result, source_pdf=pdf_path)
    output = build_final_output(normalized, output_dir=output_dir)
    output = apply_ai_enrichment(
        output=output,
        ai_base_url=ai_base_url,
        ai_api_key=ai_api_key,
        model=model,
        max_retries=max_retries,
        ai_timeout=ai_timeout,
        ai_max_failures=ai_max_failures,
    )

    output_path = output_dir / "questions_final.json"
    output_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output_path


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    output_path = run_pipeline(
        pdf_path=args.pdf,
        output_dir=args.output_dir,
        parser_name=args.parser,
        dpi=args.dpi,
        ai_base_url=args.ai_base_url,
        ai_api_key=args.ai_api_key,
        ai_timeout=args.ai_timeout,
        ai_max_failures=args.ai_max_failures,
        model=args.model,
        max_retries=args.max_retries,
    )
    print(output_path)


if __name__ == "__main__":
    main()
