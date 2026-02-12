import importlib.util
import sys
from pathlib import Path


def load_module():
    module_name = "extract_latex_with_choices_module"
    module_path = Path(__file__).resolve().parents[1] / "4_extract_all_text_and_save_latex.py"
    spec = importlib.util.spec_from_file_location(module_name, str(module_path))
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_split_question_and_choices_with_circled_numbers():
    module = load_module()
    text = """1. 다음 글을 읽고 물음에 답하시오.
지문의 핵심 내용을 고르시오.
① 첫 번째 선택지
② 두 번째 선택지"""

    question_text, choices_text = module.split_question_and_choices(text)

    assert "지문의 핵심" in question_text
    assert "① 첫 번째 선택지" in choices_text
    assert "② 두 번째 선택지" in choices_text


def test_split_question_and_choices_without_choices():
    module = load_module()
    text = """2. 다음을 설명하시오.
선택지 없이 서술형 문제입니다."""

    question_text, choices_text = module.split_question_and_choices(text)

    assert "서술형" in question_text
    assert choices_text == ""


def test_save_split_texts_writes_question_and_choices_files(tmp_path):
    module = load_module()
    out_dir = tmp_path / "split_text"
    items = [
        module.QuestionTextSet(
            index=1,
            qno=1,
            question_text="문제 본문",
            choices_text="① A\n② B",
        ),
        module.QuestionTextSet(
            index=2,
            qno=2,
            question_text="선택지 없는 문제",
            choices_text="",
        ),
    ]

    module.save_split_texts(out_dir, items)

    q1 = (out_dir / "question_001_problem.txt").read_text(encoding="utf-8")
    c1 = (out_dir / "question_001_choices.txt").read_text(encoding="utf-8")
    q2 = (out_dir / "question_002_problem.txt").read_text(encoding="utf-8")
    c2 = (out_dir / "question_002_choices.txt").read_text(encoding="utf-8")

    assert "문제 본문" in q1
    assert "① A" in c1
    assert "선택지 없는 문제" in q2
    assert c2 == ""
