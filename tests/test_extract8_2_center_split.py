import importlib.util
import sys
from pathlib import Path


def load_module():
    module_name = "extract8_2_center_split_module"
    module_path = Path(__file__).resolve().parents[1] / "8-2_extract_all_text_and_save_latex_split_images.py"
    spec = importlib.util.spec_from_file_location(module_name, str(module_path))
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_build_center_split_columns_uses_page_midpoint():
    module = load_module()

    cols = module.build_center_split_columns(page_width=700.0)

    assert cols == [(0.0, 346.0), (354.0, 700.0)]


def test_apply_center_split_first_patches_detect_page_columns(monkeypatch):
    module = load_module()

    original_columns = [[(25.0, 680.0)]]
    seen = {"separator_called": False}

    class FakeRect:
        width = 700.0

    class FakePage:
        rect = FakeRect()

    fake_doc = [FakePage()]

    def fake_apply_render_safety_patches(module5):
        module5.detect_page_columns = lambda doc: original_columns

    def fake_separator(page):
        seen["separator_called"] = True
        return None

    monkeypatch.setattr(module, "_ORIGINAL_APPLY_RENDER_SAFETY_PATCHES", fake_apply_render_safety_patches)
    monkeypatch.setattr(module._base, "detect_vertical_separator_x_in_page", fake_separator)

    module5 = type("Module5", (), {})()
    module.apply_center_split_first_patch(module5)
    out = module5.detect_page_columns(fake_doc)

    assert seen["separator_called"] is True
    assert out == [[(0.0, 346.0), (354.0, 700.0)]]


def test_apply_center_split_first_uses_separator_when_present(monkeypatch):
    module = load_module()

    class FakeRect:
        width = 720.0

    class FakePage:
        rect = FakeRect()

    fake_doc = [FakePage()]

    def fake_apply_render_safety_patches(module5):
        module5.detect_page_columns = lambda doc: [[(30.0, 690.0)]]

    monkeypatch.setattr(module, "_ORIGINAL_APPLY_RENDER_SAFETY_PATCHES", fake_apply_render_safety_patches)
    monkeypatch.setattr(module._base, "detect_vertical_separator_x_in_page", lambda page: 360.0)

    module5 = type("Module5", (), {})()
    module.apply_center_split_first_patch(module5)
    out = module5.detect_page_columns(fake_doc)

    assert out == [[(0.0, 352.0), (368.0, 720.0)]]


def test_main_delegates_with_expected_flags(monkeypatch):
    module = load_module()
    seen = {}

    def fake_main(**kwargs):
        seen.update(kwargs)

    monkeypatch.setattr(module._pipeline, "main", fake_main)
    module.main()

    assert seen == {"enable_refine": True, "enable_ocr": True, "enable_db_ready": True}


def test_main_restores_original_apply_patch(monkeypatch):
    module = load_module()
    original_apply = module._ORIGINAL_APPLY_RENDER_SAFETY_PATCHES

    monkeypatch.setattr(module._pipeline, "main", lambda **kwargs: None)
    module.main()

    assert module._base.apply_render_safety_patches is original_apply
