import importlib


def test_pipeline_submodules_are_importable():
    base = importlib.import_module("pipelines.base")
    refine = importlib.import_module("pipelines.refine")
    db_ready = importlib.import_module("pipelines.db_ready")
    ocr = importlib.import_module("pipelines.ocr")

    assert callable(base.main)
    assert callable(refine.refine_rendered_image_paths)
    assert callable(db_ready.build_db_ready_records)
    assert callable(ocr.enhance_question_texts_with_ocr)

