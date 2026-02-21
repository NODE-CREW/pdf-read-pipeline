import builtins
import sys
import types

import pipelines.base as base


def test_ocr_warns_when_python_deps_missing(monkeypatch, capsys):
    original_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "pytesseract":
            raise ModuleNotFoundError("No module named 'pytesseract'")
        return original_import(name, globals, locals, fromlist, level)

    base._OCR_WARNED_KEYS.clear()
    monkeypatch.setattr(builtins, "__import__", fake_import)

    out = base.ocr_text_from_image_paths(["/tmp/not-used.png"])
    err = capsys.readouterr().err

    assert out == ""
    assert "pytesseract/Pillow" in err


def test_ocr_warns_when_tesseract_binary_missing(monkeypatch, capsys):
    fake_pytesseract = types.SimpleNamespace(image_to_string=lambda *_args, **_kwargs: "")
    fake_pil = types.ModuleType("PIL")
    fake_pil.Image = types.SimpleNamespace(open=lambda _path: None)

    base._OCR_WARNED_KEYS.clear()
    monkeypatch.setitem(sys.modules, "pytesseract", fake_pytesseract)
    monkeypatch.setitem(sys.modules, "PIL", fake_pil)
    monkeypatch.setattr(base.shutil, "which", lambda _cmd: None)

    out = base.ocr_text_from_image_paths(["/tmp/not-used.png"])
    err = capsys.readouterr().err

    assert out == ""
    assert "tesseract 실행 파일" in err
