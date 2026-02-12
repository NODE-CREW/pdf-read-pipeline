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


def test_expand_column_bounds_preserves_neighbor_gap():
    module5 = load_module("5_extract_all_text_and_save_latex_split_images.py", "extract5_cols")
    columns = [(0.0, 260.0), (280.0, 560.0)]

    x0, x1 = module5.expand_column_bounds(columns, column_index=0, page_width=595.0)

    assert x0 == 0.0
    assert x1 <= 278.0


def test_expand_column_bounds_expands_rightmost_column():
    module5 = load_module("5_extract_all_text_and_save_latex_split_images.py", "extract5_cols_r")
    columns = [(0.0, 260.0), (280.0, 560.0)]

    x0, x1 = module5.expand_column_bounds(columns, column_index=1, page_width=595.0)

    assert x0 >= 262.0
    assert x1 > 560.0
