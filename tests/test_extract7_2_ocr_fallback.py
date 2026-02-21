import importlib.util
import sys
from pathlib import Path


def load_module():
    module_name = "extract7_2_ocr_module"
    module_path = Path(__file__).resolve().parents[1] / "7_2_extract_all_text_and_save_latex_split_images.py"
    spec = importlib.util.spec_from_file_location(module_name, str(module_path))
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_should_use_ocr_fallback_only_when_text_missing():
    module = load_module()
    assert module.should_use_ocr_fallback("\n \t", min_chars=30)
    assert not module.should_use_ocr_fallback("짧은 텍스트", min_chars=30)
    assert not module.should_use_ocr_fallback("가" * 31, min_chars=30)


def test_enhance_question_texts_with_ocr_replaces_short_text(monkeypatch):
    module = load_module()
    module5 = module.load_module_5()

    images = [
        module5.QuestionImageSet(
            index=1,
            qno=1,
            problem_image_paths=["/tmp/q1_problem.png"],
            choices_image_paths=[],
        )
    ]
    texts = [
        module5.QuestionTextSet(index=1, qno=1, question_text="", choices_text="")
    ]

    monkeypatch.setattr(
        module,
        "ocr_text_from_image_paths",
        lambda image_paths, ocr_lang="kor+eng": "1. 문제 본문\n① 보기A\n② 보기B",
    )

    out = module.enhance_question_texts_with_ocr(
        module5=module5,
        question_images=images,
        question_texts=texts,
        min_chars=30,
        ocr_lang="kor+eng",
    )

    assert len(out) == 1
    combined = f"{out[0].question_text}\n{out[0].choices_text}"
    assert "문제 본문" in combined
    assert "① 보기A" in combined


def test_enhance_question_texts_with_ocr_keeps_existing_non_empty_text(monkeypatch):
    module = load_module()
    module5 = module.load_module_5()

    images = [
        module5.QuestionImageSet(
            index=1,
            qno=1,
            problem_image_paths=["/tmp/q1_problem.png"],
            choices_image_paths=[],
        )
    ]
    short_text = "짧은 텍스트"
    texts = [
        module5.QuestionTextSet(index=1, qno=1, question_text=short_text, choices_text="")
    ]

    called = {"value": False}

    def fake_ocr(*_args, **_kwargs):
        called["value"] = True
        return ""

    monkeypatch.setattr(module, "ocr_text_from_image_paths", fake_ocr)

    out = module.enhance_question_texts_with_ocr(
        module5=module5,
        question_images=images,
        question_texts=texts,
        min_chars=30,
        ocr_lang="kor+eng",
    )

    assert out[0].question_text == short_text
    assert called["value"] is False
