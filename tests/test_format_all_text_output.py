import importlib.util
import sys
from pathlib import Path


def load_module():
    module_name = "extract_all_module"
    module_path = Path(__file__).resolve().parents[1] / "2_extract_all_text_and_print.py"
    spec = importlib.util.spec_from_file_location(module_name, str(module_path))
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_format_all_text_output_includes_page_headers():
    module = load_module()
    page_texts = [
        (0, "첫 페이지 내용"),
        (1, "둘째 페이지 내용"),
    ]

    rendered = module.format_all_text_output(page_texts)

    assert "[Page 1]" in rendered
    assert "[Page 2]" in rendered
    assert "첫 페이지 내용" in rendered
    assert "둘째 페이지 내용" in rendered


def test_format_all_text_output_handles_empty_text():
    module = load_module()
    page_texts = [
        (0, ""),
    ]

    rendered = module.format_all_text_output(page_texts)

    assert "[Page 1]" in rendered
    assert "(텍스트 없음)" in rendered
