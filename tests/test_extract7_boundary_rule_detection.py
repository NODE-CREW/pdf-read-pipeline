import importlib.util
import sys
from pathlib import Path


def load_module():
    module_name = "extract7_boundary_detection"
    module_path = Path(__file__).resolve().parents[1] / "7_extract_all_text_and_save_latex_split_images.py"
    spec = importlib.util.spec_from_file_location(module_name, str(module_path))
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_boundary_rule_detection_accepts_antialiased_long_horizontal_line():
    module7 = load_module()

    # 완전 검은 선이 아니어도, edge 근처에서 길게 이어진 수평선이면 경계선으로 본다.
    assert module7._looks_like_boundary_rule(
        mean=247.0,
        stddev=18.0,
        dark_ratio=0.35,
        longest_dark_run_ratio=0.86,
    )


def test_boundary_rule_detection_rejects_normal_text_row():
    module7 = load_module()

    assert not module7._looks_like_boundary_rule(
        mean=244.0,
        stddev=42.0,
        dark_ratio=0.14,
        longest_dark_run_ratio=0.12,
    )

