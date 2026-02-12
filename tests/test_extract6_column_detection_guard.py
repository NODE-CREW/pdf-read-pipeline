import importlib.util
import sys
from pathlib import Path


def load_module():
    module_name = "extract6_column_guard"
    module_path = Path(__file__).resolve().parents[1] / "6_extract_all_text_and_save_latex_split_images.py"
    spec = importlib.util.spec_from_file_location(module_name, str(module_path))
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_should_collapse_tight_two_columns_when_right_starts_absent():
    module6 = load_module()
    columns = [(53.0, 330.8), (334.8, 673.1)]

    assert module6.should_collapse_tight_two_columns(columns, 728.0, [100.0, 120.0]) is True


def test_should_not_collapse_when_right_starts_exist():
    module6 = load_module()
    columns = [(53.0, 330.8), (334.8, 673.1)]

    assert module6.should_collapse_tight_two_columns(columns, 728.0, [100.0, 500.0]) is False


def test_should_not_collapse_with_large_gap():
    module6 = load_module()
    columns = [(40.0, 260.0), (330.0, 560.0)]

    assert module6.should_collapse_tight_two_columns(columns, 595.0, [80.0]) is False


def test_widen_left_column_if_tight_gap():
    module6 = load_module()
    columns = [(53.0, 330.8), (334.8, 673.1)]

    x0, x1 = module6.widen_left_column_if_tight_gap(columns, 0, 728.0, 0.0, 334.3)

    assert x0 == 0.0
    assert x1 > 334.3
