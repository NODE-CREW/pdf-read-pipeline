import importlib.util
import sys
from pathlib import Path


def load_module():
    module_name = "extract8_1_saas_ocr_module"
    module_path = Path(__file__).resolve().parents[1] / "8-1_extract_all_text_and_save_latex_split_images.py"
    spec = importlib.util.spec_from_file_location(module_name, str(module_path))
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_ocr_text_from_image_paths_prefers_saas(monkeypatch):
    module = load_module()
    called = {"local": False}

    monkeypatch.setattr(
        module,
        "_ocr_text_from_image_paths_saas",
        lambda image_paths, ocr_lang="kor+eng": "1. SaaS 인식 결과\n① 보기A",
    )

    def fake_local_ocr(*_args, **_kwargs):
        called["local"] = True
        return "local"

    monkeypatch.setattr(module._base, "ocr_text_from_image_paths", fake_local_ocr)

    out = module.ocr_text_from_image_paths(["/tmp/q1.png"], ocr_lang="kor+eng")

    assert "SaaS 인식 결과" in out
    assert called["local"] is False


def test_ocr_text_from_image_paths_fallbacks_to_local(monkeypatch):
    module = load_module()
    called = {"local": False}

    monkeypatch.setattr(
        module,
        "_ocr_text_from_image_paths_saas",
        lambda image_paths, ocr_lang="kor+eng": "",
    )

    def fake_local_ocr(*_args, **_kwargs):
        called["local"] = True
        return "1. local 인식 결과\n① 보기A"

    monkeypatch.setattr(module._base, "ocr_text_from_image_paths", fake_local_ocr)

    out = module.ocr_text_from_image_paths(["/tmp/q1.png"], ocr_lang="kor+eng")

    assert "local 인식 결과" in out
    assert called["local"] is True


def test_8_1_main_delegates_with_expected_flags(monkeypatch):
    module = load_module()
    seen = {}

    def fake_main(**kwargs):
        seen.update(kwargs)

    monkeypatch.setattr(module._pipeline, "main", fake_main)
    module.main()

    assert seen == {"enable_refine": True, "enable_ocr": True, "enable_db_ready": True}
