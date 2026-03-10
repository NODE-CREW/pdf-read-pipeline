import importlib.util
import sys
from pathlib import Path


def load_module(path: str, name: str):
    module_path = Path(__file__).resolve().parents[1] / path
    spec = importlib.util.spec_from_file_location(name, str(module_path))
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_6_1_main_delegates_with_expected_flags(monkeypatch):
    module = load_module(
        "6-1_extract_all_text_and_save_latex_split_images.py",
        "entry_6_1",
    )
    seen = {}

    def fake_main(**kwargs):
        seen.update(kwargs)

    monkeypatch.setattr(module._pipeline, "main", fake_main)
    module.main()

    assert seen == {"enable_refine": False, "enable_ocr": False, "enable_db_ready": True}


def test_6_2_main_delegates_with_expected_flags(monkeypatch):
    module = load_module(
        "6-2_extract_all_text_and_save_latex_split_images.py",
        "entry_6_2",
    )
    seen = {}

    def fake_main(**kwargs):
        seen.update(kwargs)

    monkeypatch.setattr(module._pipeline, "main", fake_main)
    module.main()

    assert seen == {"enable_refine": False, "enable_ocr": True, "enable_db_ready": True}


def test_7_1_main_delegates_with_expected_flags(monkeypatch):
    module = load_module(
        "7-1_extract_all_text_and_save_latex_split_images.py",
        "entry_7_1",
    )
    seen = {}

    def fake_main(**kwargs):
        seen.update(kwargs)

    monkeypatch.setattr(module._pipeline, "main", fake_main)
    module.main()

    assert seen == {"enable_refine": True, "enable_ocr": False, "enable_db_ready": True}


def test_7_2_main_delegates_with_expected_flags(monkeypatch):
    module = load_module(
        "7-2_extract_all_text_and_save_latex_split_images.py",
        "entry_7_2",
    )
    seen = {}

    def fake_main(**kwargs):
        seen.update(kwargs)

    monkeypatch.setattr(module._pipeline, "main", fake_main)
    module.main()

    assert seen == {"enable_refine": True, "enable_ocr": True, "enable_db_ready": True}


def test_8_main_delegates_with_expected_flags(monkeypatch):
    module = load_module(
        "8_extract_all_text_and_save_latex_split_images.py",
        "entry_8",
    )
    seen = {}

    def fake_main(**kwargs):
        seen.update(kwargs)

    monkeypatch.setattr(module._pipeline, "main", fake_main)
    module.main()

    assert seen == {"enable_refine": True, "enable_ocr": True, "enable_db_ready": True}
