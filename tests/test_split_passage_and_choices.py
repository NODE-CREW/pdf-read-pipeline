import importlib.util
from pathlib import Path


def load_module():
    module_path = Path(__file__).resolve().parents[1] / "1_extract_text_and_print.py"
    spec = importlib.util.spec_from_file_location("extract_module", str(module_path))
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_split_passage_and_choices_with_circled_numbers():
    module = load_module()
    text = """1. 다음 글을 읽고 물음에 답하시오.
지문의 핵심 내용을 고르시오.
① 첫 번째 선택지
② 두 번째 선택지"""

    passage, choices = module.split_passage_and_choices(text)

    assert "지문의 핵심" in passage
    assert "① 첫 번째 선택지" in choices
    assert "② 두 번째 선택지" in choices


def test_split_passage_and_choices_without_choices():
    module = load_module()
    text = """2. 다음을 설명하시오.
선택지 없이 서술형 문제입니다."""

    passage, choices = module.split_passage_and_choices(text)

    assert "서술형" in passage
    assert choices == ""
