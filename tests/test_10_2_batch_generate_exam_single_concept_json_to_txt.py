import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


def load_module():
    module_name = "batch_generate_exam_single_concept_json_to_txt_10_2"
    module_path = (
        Path(__file__).resolve().parents[1] / "10-2_batch_generate_exam_single_concept_json_to_txt.py"
    )
    spec = importlib.util.spec_from_file_location(module_name, str(module_path))
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"placeholder")


def test_build_command_repeats_question_id_for_every_image(tmp_path):
    module = load_module()
    runner_script = tmp_path / "9-2_generate_exam_single_concept_json_to_txt.py"
    image_paths = [
        tmp_path / "question_007_problem_part_01.png",
        tmp_path / "question_007_choices_part_01.png",
        tmp_path / "question_007_choices_part_02.png",
    ]
    output_path = tmp_path / "question_007_single_concept.txt"

    command = module.build_command(
        python_executable="/usr/bin/python3",
        runner_script_path=runner_script,
        image_paths=image_paths,
        question_number=7,
        output_path=output_path,
        model="gpt-5-mini",
        max_retries=5,
    )

    assert command == [
        "/usr/bin/python3",
        str(runner_script),
        "--image",
        str(image_paths[0]),
        "--image",
        str(image_paths[1]),
        "--image",
        str(image_paths[2]),
        "--question-id",
        "7",
        "--question-id",
        "7",
        "--question-id",
        "7",
        "--output",
        str(output_path),
        "--model",
        "gpt-5-mini",
        "--max-retries",
        "5",
    ]


def test_run_batch_invokes_9_2_for_each_question_group(monkeypatch, tmp_path):
    module = load_module()
    input_dir = tmp_path / "output" / "sample" / "latex_pages"
    touch(input_dir / "question_001_choices_part_01.png")
    touch(input_dir / "question_001_problem_part_01.png")
    touch(input_dir / "question_002_problem_part_01.png")

    seen_commands = []

    def fake_run(command, check, capture_output, text):
        seen_commands.append(command)
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    output_paths = module.run_batch(
        input_dir=input_dir,
        output_dir=None,
        model="gpt-5-mini",
        max_retries=3,
        python_executable="/usr/bin/python3",
    )

    assert [path.name for path in output_paths] == [
        "question_001_single_concept.txt",
        "question_002_single_concept.txt",
    ]
    assert output_paths[0].parent == input_dir.parent / "exam_single_concept_txt"
    assert seen_commands[0][:2] == [
        "/usr/bin/python3",
        str(Path(__file__).resolve().parents[1] / "9-2_generate_exam_single_concept_json_to_txt.py"),
    ]
    assert seen_commands[0].count("--image") == 2
    assert seen_commands[0].count("--question-id") == 2
    assert seen_commands[1].count("--question-id") == 1


def test_run_batch_can_restart_from_specific_question_number(monkeypatch, tmp_path):
    module = load_module()
    input_dir = tmp_path / "latex_pages"
    touch(input_dir / "question_001_problem_part_01.png")
    touch(input_dir / "question_002_problem_part_01.png")
    touch(input_dir / "question_003_problem_part_01.png")

    seen_commands = []

    def fake_run(command, check, capture_output, text):
        seen_commands.append(command)
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    output_paths = module.run_batch(
        input_dir=input_dir,
        output_dir=None,
        model="gpt-5-mini",
        max_retries=3,
        python_executable="/usr/bin/python3",
        start_question_number=2,
    )

    assert [path.name for path in output_paths] == [
        "question_002_single_concept.txt",
        "question_003_single_concept.txt",
    ]
    assert len(seen_commands) == 2
    assert seen_commands[0][seen_commands[0].index("--question-id") + 1] == "2"


def test_run_batch_raises_runtime_error_when_subprocess_fails(monkeypatch, tmp_path):
    module = load_module()
    input_dir = tmp_path / "latex_pages"
    touch(input_dir / "question_003_problem_part_01.png")

    def fake_run(command, check, capture_output, text):
        return subprocess.CompletedProcess(
            args=command,
            returncode=1,
            stdout="",
            stderr="boom",
        )

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="question_003"):
        module.run_batch(
            input_dir=input_dir,
            output_dir=None,
            model="gpt-5-mini",
            max_retries=3,
            python_executable="/usr/bin/python3",
        )
