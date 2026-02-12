import importlib.util
import sys
from pathlib import Path



def load_module():
    module_name = "extract_latex_split_images_module_6"
    module_path = (
        Path(__file__).resolve().parents[1] / "6_extract_all_text_and_save_latex_split_images.py"
    )
    spec = importlib.util.spec_from_file_location(module_name, str(module_path))
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_parse_osascript_output_filters_empty_lines():
    module = load_module()
    stdout = "\n/Users/me/a.pdf\n\n/Users/me/b.pdf\n"

    assert module._parse_osascript_output(stdout) == ["/Users/me/a.pdf", "/Users/me/b.pdf"]


def test_select_pdf_files_with_osascript_cancel_returns_empty(monkeypatch):
    module = load_module()

    class Proc:
        returncode = 1
        stdout = ""
        stderr = "execution error: User canceled."

    monkeypatch.setattr(module.sys, "platform", "darwin")
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: Proc())

    assert module.select_pdf_files_with_osascript() == []


def test_select_pdf_files_with_osascript_success(monkeypatch):
    module = load_module()

    class Proc:
        returncode = 0
        stdout = "/Users/me/a.pdf\n/Users/me/b.pdf\n"
        stderr = ""

    monkeypatch.setattr(module.sys, "platform", "darwin")
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: Proc())

    assert module.select_pdf_files_with_osascript() == ["/Users/me/a.pdf", "/Users/me/b.pdf"]
