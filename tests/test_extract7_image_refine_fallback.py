import builtins
import importlib.util
import sys
from pathlib import Path


def load_module():
    module_name = "extract7_image_refine_fallback"
    module_path = Path(__file__).resolve().parents[1] / "7_extract_all_text_and_save_latex_split_images.py"
    spec = importlib.util.spec_from_file_location(module_name, str(module_path))
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_refine_image_page_boundaries_uses_fitz_fallback_when_pillow_missing(
    monkeypatch, tmp_path
):
    module7 = load_module()
    image_path = tmp_path / "dummy.png"
    image_path.write_bytes(b"dummy")

    original_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "PIL":
            raise ImportError("Pillow missing")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.setattr(
        module7,
        "_refine_image_page_boundaries_with_fitz",
        lambda _path, **_kwargs: True,
    )

    assert module7.refine_image_page_boundaries(image_path) is True
    assert module7._PIL_IMAGE_AVAILABLE is False


def test_refine_image_page_boundaries_returns_false_when_file_missing():
    module7 = load_module()
    assert module7.refine_image_page_boundaries("/path/does/not/exist.png") is False


def test_refine_rendered_image_paths_still_runs_when_pillow_flag_false(monkeypatch):
    module7 = load_module()
    module7._PIL_IMAGE_AVAILABLE = False

    monkeypatch.setattr(module7, "refine_image_page_boundaries", lambda _path: True)

    count = module7.refine_rendered_image_paths(["a.png", "b.png"])
    assert count == 2
