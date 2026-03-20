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


def test_build_two_columns_from_separator():
    import pipelines.base as base

    cols = base.build_two_columns_from_separator(page_width=700.0, separator_x=350.0)

    assert len(cols) == 2
    assert cols[0][1] < 350.0
    assert cols[1][0] > 350.0


def test_infer_vertical_separator_x_detects_center_band():
    import pipelines.base as base

    def fake_col_stats(x: int):
        if 345 <= x <= 355:
            return 120.0, 2.0, 0.95, 0.98
        return 250.0, 50.0, 0.02, 0.05

    split_x = base.infer_vertical_separator_x(
        image_width=700,
        col_stats_fn=fake_col_stats,
    )

    assert split_x is not None
    assert 345.0 <= split_x <= 355.0


def test_rebuild_unbalanced_two_columns_from_question_starts_repairs_narrow_left_column():
    import pipelines.base as base

    cols = base.rebuild_unbalanced_two_columns_from_question_starts(
        columns=[(18.7, 154.7), (158.7, 576.6)],
        page_width=595.0,
        question_start_x_centers=[152.0, 154.0, 155.0, 434.0, 438.0],
    )

    assert len(cols) == 2
    assert cols[0][1] > 250.0
    assert cols[1][0] > cols[0][1]


def test_rebuild_unbalanced_two_columns_from_question_starts_keeps_balanced_columns():
    import pipelines.base as base

    cols = base.rebuild_unbalanced_two_columns_from_question_starts(
        columns=[(0.0, 290.0), (305.0, 595.0)],
        page_width=595.0,
        question_start_x_centers=[150.0, 160.0, 440.0],
    )

    assert cols == [(0.0, 290.0), (305.0, 595.0)]
