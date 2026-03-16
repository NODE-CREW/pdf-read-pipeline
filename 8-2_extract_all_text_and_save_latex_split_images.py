#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pipelines.split_images_pipeline import *  # noqa: F401,F403
import pipelines.split_images_pipeline as _pipeline
import pipelines.base as _base


_ORIGINAL_APPLY_RENDER_SAFETY_PATCHES = _base.apply_render_safety_patches


def build_center_split_columns(
    page_width: float,
    separator_half_gap: float = 4.0,
) -> list[tuple[float, float]]:
    return _base.build_two_columns_from_separator(
        page_width=page_width,
        separator_x=page_width / 2.0,
        separator_half_gap=separator_half_gap,
    )


def apply_center_split_first_patch(module5) -> None:
    _ORIGINAL_APPLY_RENDER_SAFETY_PATCHES(module5)

    original_detect_page_columns = getattr(module5, "detect_page_columns", None)
    if original_detect_page_columns is None:
        return

    def detect_page_columns_with_center_split_first(doc):
        page_columns = original_detect_page_columns(doc)
        patched_columns: list[list[tuple[float, float]]] = []

        for page_idx, page in enumerate(doc):
            page_width = float(page.rect.width)
            separator_x = _base.detect_vertical_separator_x_in_page(page)
            if separator_x is not None:
                patched_columns.append(
                    _base.build_two_columns_from_separator(
                        page_width=page_width,
                        separator_x=separator_x,
                    )
                )
                continue

            center_columns = build_center_split_columns(page_width=page_width)
            if len(center_columns) == 2:
                patched_columns.append(center_columns)
                continue

            patched_columns.append(page_columns[page_idx])

        return patched_columns

    module5.detect_page_columns = detect_page_columns_with_center_split_first


def process_one_pdf(module5, pdf_path: str, output_root, dpi: int):
    return _pipeline.process_one_pdf(
        module5,
        pdf_path=pdf_path,
        output_root=output_root,
        dpi=dpi,
        enable_refine=True,
        enable_ocr=True,
        enable_db_ready=True,
    )


def main() -> None:
    _base.apply_render_safety_patches = apply_center_split_first_patch
    try:
        _pipeline.main(enable_refine=True, enable_ocr=True, enable_db_ready=True)
    finally:
        _base.apply_render_safety_patches = _ORIGINAL_APPLY_RENDER_SAFETY_PATCHES


if __name__ == "__main__":
    main()
