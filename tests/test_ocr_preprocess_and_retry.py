import sys
import types

import pipelines.base as base


class _FakeImage:
    size = (800, 1200)

    def convert(self, _mode):
        return self

    def point(self, _fn):
        return self

    def crop(self, _box):
        return self


class _FakeImageContext:
    def __enter__(self):
        return _FakeImage()

    def __exit__(self, exc_type, exc, tb):
        return False


def test_ocr_uses_preprocessed_image(monkeypatch):
    calls = []

    def fake_image_to_string(image, lang="kor+eng", config=""):
        calls.append({"image": image, "lang": lang, "config": config})
        return "문항 텍스트"

    fake_pytesseract = types.SimpleNamespace(image_to_string=fake_image_to_string)
    fake_pil = types.ModuleType("PIL")
    fake_pil.Image = types.SimpleNamespace(open=lambda _path: _FakeImageContext())

    monkeypatch.setitem(sys.modules, "pytesseract", fake_pytesseract)
    monkeypatch.setitem(sys.modules, "PIL", fake_pil)
    monkeypatch.setattr(base.shutil, "which", lambda _cmd: "/opt/homebrew/bin/tesseract")

    text = base.ocr_text_from_image_paths(["/tmp/q1.png"], ocr_lang="kor+eng")

    assert "문항 텍스트" in text
    assert calls
    assert calls[0]["config"] == "--oem 1 --psm 6"


def test_ocr_retries_with_second_psm_when_first_result_empty(monkeypatch):
    calls = []

    def fake_image_to_string(_image, lang="kor+eng", config=""):
        calls.append(config)
        if config == "--oem 1 --psm 6":
            return " \n "
        if config == "--oem 1 --psm 4":
            return "재시도 성공"
        return ""

    fake_pytesseract = types.SimpleNamespace(image_to_string=fake_image_to_string)
    fake_pil = types.ModuleType("PIL")
    fake_pil.Image = types.SimpleNamespace(open=lambda _path: _FakeImageContext())

    monkeypatch.setitem(sys.modules, "pytesseract", fake_pytesseract)
    monkeypatch.setitem(sys.modules, "PIL", fake_pil)
    monkeypatch.setattr(base.shutil, "which", lambda _cmd: "/opt/homebrew/bin/tesseract")

    text = base.ocr_text_from_image_paths(["/tmp/q1.png"], ocr_lang="kor+eng")

    assert text == "재시도 성공"
    assert calls == ["--oem 1 --psm 6", "--oem 1 --psm 4"]
