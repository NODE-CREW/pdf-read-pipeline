#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
from pathlib import Path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_dir", help="합칠 txt 파일이 들어 있는 디렉토리")
    parser.add_argument("--output", required=True, help="합친 결과를 저장할 txt 파일 경로")
    return parser.parse_args(argv)


def validate_input_dir(input_dir: str) -> Path:
    resolved = Path(input_dir).expanduser().resolve()
    if not resolved.exists() or not resolved.is_dir():
        raise ValueError("입력 디렉토리가 존재하지 않거나 디렉토리가 아니다.")
    return resolved


def resolve_output_path(output_path: str) -> Path:
    return Path(output_path).expanduser().resolve()


def collect_text_files(*, input_dir: Path, output_path: Path) -> list[Path]:
    text_files = []
    for path in sorted(input_dir.iterdir(), key=lambda item: item.name):
        if not path.is_file():
            continue
        if path.suffix.lower() != ".txt":
            continue
        if path.resolve() == output_path:
            continue
        text_files.append(path.resolve())

    if not text_files:
        raise ValueError("합칠 txt 파일을 찾을 수 없다.")
    return text_files


def concat_text_contents(text_paths: list[Path]) -> str:
    merged_parts: list[str] = []

    for path in text_paths:
        content = path.read_text(encoding="utf-8")
        if merged_parts and merged_parts[-1] and not merged_parts[-1].endswith("\n") and content:
            merged_parts.append("\n")
        merged_parts.append(content)

    return "".join(merged_parts)


def run(*, input_dir: Path, output_path: Path) -> Path:
    resolved_input_dir = validate_input_dir(str(input_dir))
    resolved_output_path = resolve_output_path(str(output_path))
    text_files = collect_text_files(
        input_dir=resolved_input_dir,
        output_path=resolved_output_path,
    )
    merged_text = concat_text_contents(text_files)
    resolved_output_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_output_path.write_text(merged_text, encoding="utf-8")
    return resolved_output_path


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    output_path = run(
        input_dir=Path(args.input_dir),
        output_path=Path(args.output),
    )
    print(f"{output_path} 저장 완료")


if __name__ == "__main__":
    main()
