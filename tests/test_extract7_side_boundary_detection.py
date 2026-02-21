import importlib.util
import sys
from pathlib import Path


def load_module():
    module_name = "extract7_side_boundary_detection"
    module_path = Path(__file__).resolve().parents[1] / "7_extract_all_text_and_save_latex_split_images.py"
    spec = importlib.util.spec_from_file_location(module_name, str(module_path))
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_find_side_trim_detects_left_vertical_rule_away_from_edge():
    module7 = load_module()

    width = 120

    def col_stats(x: int):
        # x=18 열에 세로 경계선이 있다고 가정
        if x == 18:
            return (210.0, 6.0, 0.88, 0.96)
        return (252.0, 40.0, 0.05, 0.05)

    trim = module7._find_side_trim_by_column_stats(
        image_width=width,
        from_left=True,
        max_trim_px=40,
        edge_scan_cols=48,
        col_stats_fn=col_stats,
    )

    assert trim >= 19


def test_find_side_trim_returns_zero_without_vertical_rule():
    module7 = load_module()

    trim = module7._find_side_trim_by_column_stats(
        image_width=120,
        from_left=True,
        max_trim_px=40,
        edge_scan_cols=48,
        col_stats_fn=lambda _x: (252.0, 40.0, 0.08, 0.08),
    )

    assert trim == 0

