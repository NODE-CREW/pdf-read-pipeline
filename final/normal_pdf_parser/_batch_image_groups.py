#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import re
import subprocess
import sys
from pathlib import Path


QUESTION_IMAGE_PATTERN = re.compile(r"^question_(\d{3})_.+\.(png|jpg|jpeg|webp)$", re.IGNORECASE)
PART_PATTERN = re.compile(r"_part_(\d+)", re.IGNORECASE)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_dir", help="question_XXX_* 이미지가 들어 있는 디렉토리")
    parser.add_argument(
        "--output-dir",
        help="결과 txt 저장 디렉토리. 생략하면 input_dir 상위에 exam_concepts_txt를 사용",
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
    resolved = Path(input_dir).expanduser().resolve()
    if not resolved.exists() or not resolved.is_dir():
        raise ValueError("입력 디렉토리가 존재하지 않거나 디렉토리가 아니다.")
    return resolved


def get_runner_script_path() -> Path:
    return Path(__file__).resolve().with_name("generate_concept.py")


def build_output_dir(*, input_dir: Path, output_dir: str | None) -> Path:
    if output_dir:
        return Path(output_dir).expanduser().resolve()
    return input_dir.parent / "exam_concepts_txt"


def extract_part_number(path: Path) -> int:
    match = PART_PATTERN.search(path.stem)
    if match is None:
        return 0
    return int(match.group(1))


def build_image_sort_key(path: Path) -> tuple[int, int, str]:
    name = path.name.lower()
    if "_problem_" in name:
        kind_priority = 0
    elif "_choices_" in name:
        kind_priority = 1
    else:
        kind_priority = 2
    return (kind_priority, extract_part_number(path), path.name)


def collect_question_image_groups(input_dir: Path) -> list[tuple[int, list[Path]]]:
    grouped_paths: dict[int, list[Path]] = {}

    for path in sorted(input_dir.iterdir(), key=lambda item: item.name):
        if not path.is_file():
            continue
        match = QUESTION_IMAGE_PATTERN.match(path.name)
        if match is None:
            continue
        question_number = int(match.group(1))
        grouped_paths.setdefault(question_number, []).append(path)

    if not grouped_paths:
        raise ValueError("question_XXX_* 형식의 이미지 파일을 찾을 수 없다.")

    return [
        (question_number, sorted(image_paths, key=build_image_sort_key))
        for question_number, image_paths in sorted(grouped_paths.items())
    ]


def filter_question_groups(
    question_groups: list[tuple[int, list[Path]]],
    start_question_number: int | None,
) -> list[tuple[int, list[Path]]]:
    if start_question_number is None:
        return question_groups
    if start_question_number <= 0:
        raise ValueError("시작할 문제 번호는 1 이상의 정수여야 한다.")

    for index, (question_number, _) in enumerate(question_groups):
        if question_number == start_question_number:
            return question_groups[index:]

    raise ValueError("시작할 문제 번호에 해당하는 question_XXX_* 파일을 찾을 수 없다.")


def build_output_path(*, output_dir: Path, question_number: int) -> Path:
    return output_dir / f"question_{question_number:03d}_concepts.txt"


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
    resolved_output_dir = build_output_dir(input_dir=resolved_input_dir, output_dir=output_dir)
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    runner_script_path = get_runner_script_path()
    question_groups = filter_question_groups(
        collect_question_image_groups(resolved_input_dir),
        start_question_number,
    )

    output_paths = []
    for question_number, image_paths in question_groups:
        output_path = build_output_path(output_dir=resolved_output_dir, question_number=question_number)
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
