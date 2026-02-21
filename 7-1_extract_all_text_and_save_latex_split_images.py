#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pipelines.split_images_pipeline import *  # noqa: F401,F403
import pipelines.split_images_pipeline as _pipeline


def process_one_pdf(module5, pdf_path: str, output_root: Path, dpi: int) -> Path:
    return _pipeline.process_one_pdf(
        module5,
        pdf_path=pdf_path,
        output_root=output_root,
        dpi=dpi,
        enable_refine=True,
        enable_ocr=False,
        enable_db_ready=True,
    )


def main() -> None:
    _pipeline.main(enable_refine=True, enable_ocr=False, enable_db_ready=True)


if __name__ == "__main__":
    main()
