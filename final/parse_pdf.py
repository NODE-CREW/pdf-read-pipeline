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
from final.text_refiner import collect_question_text_artifacts, refine_question_text


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
    parser.add_argument("--ai-timeout", type=float, default=60.0, help="AI 요청 timeout 초")
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
    parser.add_argument(
        "--skip-text-refine",
        action="store_true",
        help="AI endpoint가 있어도 문제/선지 텍스트 LLM 정제를 건너뜀",
    )
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
    ai_timeout: float = 60.0,
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
    output["metadata"]["requires_answer_review"] = (
        output["metadata"].get("requires_answer_review", False)
        or any(
            question["options"] and not any(option["is_correct"] for option in question["options"])
            for question in output["questions"]
        )
        or bool(ai_errors)
    )
    output["metadata"]["ai_enrichment"] = {
        "enabled": True,
        "failed_questions": len(ai_errors),
        "skipped_questions": skipped_questions,
        "errors": ai_errors[:10],
    }
    validate_final_output(output)
    return output


def apply_text_refinement(
    *,
    output: dict[str, Any],
    ai_base_url: str | None,
    ai_api_key: str,
    model: str,
    max_retries: int,
    ai_timeout: float = 60.0,
    ai_max_failures: int = 3,
    enabled: bool = True,
) -> dict[str, Any]:
    if not ai_base_url or not enabled:
        output["metadata"]["text_refinement"] = {"enabled": False}
        return output

    client = create_openai_client(base_url=ai_base_url, api_key=ai_api_key, timeout=ai_timeout)
    errors: list[dict[str, str]] = []
    timeout_errors: list[dict[str, str]] = []
    refined_questions: list[dict[str, Any]] = []
    low_confidence_questions: list[dict[str, str]] = []
    unresolved_artifacts: list[dict[str, Any]] = []
    skipped_questions = 0
    for index, question in enumerate(output["questions"]):
        if len(errors) >= max(ai_max_failures, 1):
            skipped_questions = len(output["questions"]) - index
            print(
                f"[text-refine skipped] {skipped_questions} questions skipped "
                f"after {len(errors)} failures.",
                file=sys.stderr,
            )
            break
        question_source = question.get("question_source", "")
        try:
            refinement = refine_question_text(
                client=client,
                model=model,
                question=question,
                max_retries=max_retries,
            )
        except Exception as exc:
            error_text = str(exc)
            print(
                f"[text-refine failed] {question_source}: {error_text}",
                file=sys.stderr,
            )
            if is_timeout_error(exc):
                timeout_errors.append(
                    {
                        "question_source": str(question_source),
                        "error": error_text,
                    }
                )
                continue
            errors.append(
                {
                    "question_source": str(question_source),
                    "error": error_text,
                }
            )
            continue

        confidence = str(refinement.get("confidence", "medium"))
        corrections = refinement.get("corrections", [])
        changes = refinement.get("changes", [])
        if changes:
            log_text_refinement_changes(str(question_source), changes)
        if corrections or changes:
            refined_questions.append(
                {
                    "question_source": str(question_source),
                    "confidence": confidence,
                    "corrections": corrections,
                    "changes": changes,
                }
            )
        if confidence == "low":
            low_confidence_questions.append(
                {
                    "question_source": str(question_source),
                    "reason": "LLM 텍스트 정제 신뢰도가 낮음",
                }
            )

        artifacts = collect_question_text_artifacts(question)
        if artifacts or confidence == "low":
            unresolved_artifacts.append(
                {
                    "question_source": str(question_source),
                    "artifacts": artifacts,
                    "confidence": confidence,
                }
            )

    output["metadata"]["requires_answer_review"] = (
        output["metadata"].get("requires_answer_review", False)
        or bool(errors)
        or bool(timeout_errors)
        or bool(low_confidence_questions)
        or bool(unresolved_artifacts)
    )
    output["metadata"]["text_refinement"] = {
        "enabled": True,
        "failed_questions": len(errors),
        "timeout_questions": len(timeout_errors),
        "skipped_questions": skipped_questions,
        "refined_questions": refined_questions[:50],
        "low_confidence_questions": low_confidence_questions[:50],
        "unresolved_artifact_questions": len(unresolved_artifacts),
        "unresolved_artifacts": unresolved_artifacts[:10],
        "errors": errors[:10],
        "timeout_errors": timeout_errors[:10],
    }
    validate_final_output(output)
    return output


def log_text_refinement_changes(question_source: str, changes: list[dict[str, Any]]) -> None:
    for change in changes:
        field = change.get("field")
        if field == "option":
            label = f"option {change.get('order')}"
        else:
            label = str(field)
        print(
            "[text-refine changed] "
            f"{question_source} / {label}\n"
            f"- before: {change.get('before', '')}\n"
            f"- after: {change.get('after', '')}",
            file=sys.stderr,
        )


def is_timeout_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return "timed out" in text or "timeout" in text


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
    ai_timeout: float = 60.0,
    ai_max_failures: int = 3,
    refine_text: bool = True,
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
    output = apply_text_refinement(
        output=output,
        ai_base_url=ai_base_url,
        ai_api_key=ai_api_key,
        model=model,
        max_retries=max_retries,
        ai_timeout=ai_timeout,
        ai_max_failures=ai_max_failures,
        enabled=refine_text,
    )
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
        refine_text=not args.skip_text_refine,
    )
    print(output_path)


if __name__ == "__main__":
    main()
