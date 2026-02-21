#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pipelines.split_images_pipeline import *  # noqa: F401,F403
import pipelines.split_images_pipeline as _pipeline
import pipelines.base as _base


ocr_text_from_image_paths = _base.ocr_text_from_image_paths


def enhance_question_texts_with_ocr(
    module5,
    question_images,
    question_texts,
    min_chars: int = 30,
    ocr_lang: str = "kor+eng",
):
    original_ocr = _base.ocr_text_from_image_paths
    _base.ocr_text_from_image_paths = ocr_text_from_image_paths
    try:
        return _base.enhance_question_texts_with_ocr(
            module5=module5,
            question_images=question_images,
            question_texts=question_texts,
            min_chars=min_chars,
            ocr_lang=ocr_lang,
        )
    finally:
        _base.ocr_text_from_image_paths = original_ocr


def process_one_pdf(module5, pdf_path: str, output_root: Path, dpi: int) -> Path:
    return _pipeline.process_one_pdf(
        module5,
        pdf_path=pdf_path,
        output_root=output_root,
        dpi=dpi,
        enable_refine=False,
        enable_ocr=True,
        enable_db_ready=True,
    )


def main() -> None:
    _pipeline.main(enable_refine=False, enable_ocr=True, enable_db_ready=True)


if __name__ == "__main__":
    main()
