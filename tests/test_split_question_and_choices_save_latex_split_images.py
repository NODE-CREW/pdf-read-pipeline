import importlib.util
import sys
from pathlib import Path


def load_module():
    module_name = "extract_latex_split_images_module"
    module_path = (
        Path(__file__).resolve().parents[1] / "5_extract_all_text_and_save_latex_split_images.py"
    )
    spec = importlib.util.spec_from_file_location(module_name, str(module_path))
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_split_problem_and_choices_clip_by_choice_blocks():
    module = load_module()
    problem, choices = module.split_problem_and_choices_clip_by_choice_blocks(
        clip_y0=100.0,
        clip_y1=320.0,
        text_blocks=[
            (110.0, 150.0, "지문 내용"),
            (205.0, 240.0, "① 보기 A\\n② 보기 B"),
        ],
    )

    assert problem is not None
    assert choices is not None
    assert problem[0] == 100.0
    assert problem[1] < 210.0
    assert choices[0] >= 200.0
    assert choices[1] == 320.0


def test_split_problem_and_choices_clip_without_choice_blocks():
    module = load_module()
    problem, choices = module.split_problem_and_choices_clip_by_choice_blocks(
        clip_y0=50.0,
        clip_y1=180.0,
        text_blocks=[
            (60.0, 90.0, "선택지 없는 서술형 문항"),
        ],
    )

    assert problem == (50.0, 180.0)
    assert choices is None


def test_build_latex_document_contains_problem_and_choices_images():
    module = load_module()
    question_images = [
        module.QuestionImageSet(
            index=1,
            qno=2,
            problem_image_paths=["questions/question_001_problem_part_01.png"],
            choices_image_paths=["questions/question_001_choices_part_01.png"],
        )
    ]

    tex = module.build_latex_document(pdf_name="level2.pdf", question_images=question_images)

    assert r"\\subsection*{Problem}" in tex
    assert r"\\subsection*{Choices}" in tex
    assert "question_001_problem_part_01.png" in tex
    assert "question_001_choices_part_01.png" in tex


def test_is_valid_question_start_line_rejects_formula_tail_lines():
    module = load_module()

    assert module.is_valid_question_start_line("35. 다음 중 이름 상자에 대한 설명으로 옳지 않은 것은?")
    assert module.is_valid_question_start_line("1.이윤극대화를 추구하는 기업")
    assert not module.is_valid_question_start_line("1)))}")
    assert not module.is_valid_question_start_line("1))}")
