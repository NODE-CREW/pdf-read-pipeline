import importlib.util
import sys
from pathlib import Path


def load_module(filename: str, module_name: str):
    module_path = Path(__file__).resolve().parents[1] / filename
    spec = importlib.util.spec_from_file_location(module_name, str(module_path))
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_refine_clip_x_keeps_right_edge_when_gap_is_small():
    module4 = load_module("4_extract_all_text_and_save_latex.py", "extract4")
    module5 = load_module("5_extract_all_text_and_save_latex_split_images.py", "extract5")

    boxes = [(30.0, 10.0, 285.0, 120.0)]

    x0_4, x1_4 = module4.refine_clip_x_to_text_blocks(0.0, 300.0, boxes)
    x0_5, x1_5 = module5.refine_clip_x_to_text_blocks(0.0, 300.0, boxes)

    assert x1_4 == 300.0
    assert x1_5 == 300.0


def test_refine_clip_x_trims_large_blank_margin():
    module4 = load_module("4_extract_all_text_and_save_latex.py", "extract4_trim")
    module5 = load_module("5_extract_all_text_and_save_latex_split_images.py", "extract5_trim")

    boxes = [(50.0, 10.0, 200.0, 120.0)]

    x0_4, x1_4 = module4.refine_clip_x_to_text_blocks(0.0, 300.0, boxes)
    x0_5, x1_5 = module5.refine_clip_x_to_text_blocks(0.0, 300.0, boxes)

    assert x0_4 > 0.0
    assert x0_5 > 0.0
    assert x1_4 < 300.0
    assert x1_5 < 300.0
