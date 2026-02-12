import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace


def load_module():
    module_name = "extract6_module"
    module_path = Path(__file__).resolve().parents[1] / "6_extract_all_text_and_save_latex_split_images.py"
    spec = importlib.util.spec_from_file_location(module_name, str(module_path))
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_apply_render_safety_patches_keeps_right_edge_for_small_trim():
    module6 = load_module()

    dummy = SimpleNamespace(
        refine_clip_x_to_text_blocks=lambda raw_x0, raw_x1, _boxes: (raw_x0 + 2.0, raw_x1 - 10.0),
        expand_column_bounds=lambda cols, idx, pw, margin=18.0, gap_guard=2.0: (10.0, 20.0),
    )

    module6.apply_render_safety_patches(dummy)
    x0, x1 = dummy.refine_clip_x_to_text_blocks(0.0, 300.0, [])

    assert x0 == 0.0
    assert x1 == 300.0


def test_apply_render_safety_patches_enforces_column_margin_floor():
    module6 = load_module()

    seen = {}

    def fake_expand(_cols, _idx, _pw, margin=18.0, gap_guard=2.0):
        seen["margin"] = margin
        seen["gap_guard"] = gap_guard
        return (0.0, 1.0)

    dummy = SimpleNamespace(
        refine_clip_x_to_text_blocks=lambda raw_x0, raw_x1, _boxes: (raw_x0, raw_x1),
        expand_column_bounds=fake_expand,
    )

    module6.apply_render_safety_patches(dummy)
    dummy.expand_column_bounds([(0.0, 10.0)], 0, 100.0, margin=12.0, gap_guard=3.0)

    assert seen["margin"] == 72.0
    assert seen["gap_guard"] == 0.5
