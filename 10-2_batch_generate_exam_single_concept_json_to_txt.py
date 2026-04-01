#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import importlib.util
import subprocess
import sys
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def load_shared_batch_module():
    module_path = Path(__file__).resolve().with_name(
        "10-1_batch_generate_exam_concepts_json_to_txt.py"
    )
    spec = importlib.util.spec_from_file_location(
        "batch_generate_exam_concepts_shared",
        module_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("공통 배치 유틸 모듈을 불러올 수 없다.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_dir", help="question_XXX_* 이미지가 들어 있는 디렉토리")
    parser.add_argument(
        "--output-dir",
        help="결과 txt 저장 디렉토리. 생략하면 input_dir 상위에 exam_single_concept_txt를 사용",
    )
    parser.add_argument(
        "--start-question-number",
        type=int,
        help="이 문제번호부터 다시 시작. 해당 번호의 question_XXX_* 파일이 실제로 있어야 함",
    )
    parser.add_argument("--model", default="gpt-5-mini", help='기본값은 "gpt-5-mini"')
    parser.add_argument("--max-retries", type=int, default=3, help="개별 호출당 최대 재시도 횟수")
    return parser.parse_args(argv)


def validate_input_dir(input_dir: str) -> Path:
    return load_shared_batch_module().validate_input_dir(input_dir)


def collect_question_image_groups(input_dir: Path) -> list[tuple[int, list[Path]]]:
    return load_shared_batch_module().collect_question_image_groups(input_dir)


def filter_question_groups(
    question_groups: list[tuple[int, list[Path]]],
    start_question_number: int | None,
) -> list[tuple[int, list[Path]]]:
    return load_shared_batch_module().filter_question_groups(
        question_groups,
        start_question_number,
    )


def get_runner_script_path() -> Path:
    return Path(__file__).resolve().with_name("9-2_generate_exam_single_concept_json_to_txt.py")


def build_output_dir(*, input_dir: Path, output_dir: str | None) -> Path:
    if output_dir:
        return Path(output_dir).expanduser().resolve()
    return input_dir.parent / "exam_single_concept_txt"


def build_output_path(*, output_dir: Path, question_number: int) -> Path:
    return output_dir / f"question_{question_number:03d}_single_concept.txt"


def build_command(
    *,
    python_executable: str,
    runner_script_path: Path,
    image_paths: list[Path],
    question_number: int,
    output_path: Path,
    model: str,
    max_retries: int,
) -> list[str]:
    command = [python_executable, str(runner_script_path)]
    for image_path in image_paths:
        command.extend(["--image", str(image_path)])
    for _ in image_paths:
        command.extend(["--question-id", str(question_number)])
    command.extend(
        [
            "--output",
            str(output_path),
            "--model",
            model,
            "--max-retries",
            str(max(max_retries, 1)),
        ]
    )
    return command


def run_question_group(command: list[str], *, question_number: int) -> None:
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode == 0:
        return

    stderr = result.stderr.strip()
    stdout = result.stdout.strip()
    details = stderr or stdout or "오류 메시지 없음"
    raise RuntimeError(f"question_{question_number:03d} 실행 실패: {details}")


def run_batch(
    *,
    input_dir: Path,
    output_dir: str | None,
    model: str,
    max_retries: int,
    python_executable: str,
    start_question_number: int | None = None,
) -> list[Path]:
    resolved_input_dir = validate_input_dir(str(input_dir))
    resolved_output_dir = build_output_dir(
        input_dir=resolved_input_dir,
        output_dir=output_dir,
    )
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    runner_script_path = get_runner_script_path()
    question_groups = filter_question_groups(
        collect_question_image_groups(resolved_input_dir),
        start_question_number,
    )

    output_paths = []
    for question_number, image_paths in question_groups:
        output_path = build_output_path(
            output_dir=resolved_output_dir,
            question_number=question_number,
        )
        command = build_command(
            python_executable=python_executable,
            runner_script_path=runner_script_path,
            image_paths=image_paths,
            question_number=question_number,
            output_path=output_path,
            model=model,
            max_retries=max_retries,
        )
        print(f"question_{question_number:03d} 실행 중: 이미지 {len(image_paths)}장")
        run_question_group(command, question_number=question_number)
        output_paths.append(output_path)

    return output_paths


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    output_paths = run_batch(
        input_dir=Path(args.input_dir),
        output_dir=args.output_dir,
        model=args.model,
        max_retries=args.max_retries,
        python_executable=sys.executable,
        start_question_number=args.start_question_number,
    )
    print(f"총 {len(output_paths)}개 문제 실행 완료")


if __name__ == "__main__":
    main()
