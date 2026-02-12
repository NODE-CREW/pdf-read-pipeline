import importlib.util
import sys
from pathlib import Path


def load_module():
    module_name = "extract_latex_module"
    module_path = Path(__file__).resolve().parents[1] / "3_extract_all_text_and_save_latex.py"
    spec = importlib.util.spec_from_file_location(module_name, str(module_path))
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_escape_latex_text():
    module = load_module()
    raw = "# $ % & _ { } ~ ^ \\"
    escaped = module.escape_latex_text(raw)

    assert r"\#" in escaped
    assert r"\$" in escaped
    assert r"\%" in escaped
    assert r"\&" in escaped
    assert r"\_" in escaped
    assert r"\{" in escaped
    assert r"\}" in escaped
    assert r"\textasciitilde{}" in escaped
    assert r"\textasciicircum{}" in escaped
    assert r"\textbackslash{}" in escaped


def test_question_start_regex_accepts_no_space_after_number():
    module = load_module()
    assert module.QUESTION_START_RE.match("1.이윤극대화를 추구하는 기업")
    assert not module.QUESTION_START_RE.match("2025년군무원채용시험")


def test_should_render_segment_skips_tiny_continuation():
    module = load_module()
    assert module.should_render_segment(part_index=1, segment_height=50.0)
    assert not module.should_render_segment(part_index=2, segment_height=60.0)
    assert not module.should_render_segment(part_index=2, segment_height=120.0)
    assert module.should_render_segment(part_index=2, segment_height=180.0)


def test_build_latex_document_contains_pages():
    module = load_module()
    question_images = [
        module.QuestionImageSet(index=1, qno=1, rel_image_paths=["questions/q_001_p01.png"]),
        module.QuestionImageSet(
            index=2,
            qno=2,
            rel_image_paths=["questions/q_002_p01.png", "questions/q_002_p02.png"],
        ),
    ]
    tex = module.build_latex_document(
        pdf_name="level2.pdf",
        question_images=question_images,
    )

    assert r"\title{PDF to LaTeX (Image-based)}" in tex
    assert r"\section*{Question 1 (No. 1)}" in tex
    assert r"\section*{Question 2 (No. 2)}" in tex
    assert r"\includegraphics[width=\textwidth]{questions/q_001_p01.png}" in tex
    assert r"\includegraphics[width=\textwidth]{questions/q_002_p02.png}" in tex


def test_infer_columns_from_ranges_two_column_layout():
    module = load_module()
    columns = module.infer_columns_from_ranges(
        block_ranges=[(20.0, 280.0), (30.0, 290.0), (330.0, 600.0), (340.0, 610.0)],
        page_width=620.0,
    )
    assert len(columns) == 2
    assert columns[0][0] < 40.0
    assert columns[0][1] < 330.0
    assert columns[1][0] > 300.0


def test_build_question_spans_across_columns():
    module = load_module()
    starts = [
        module.QuestionStart(page_index=0, column=0, y0=100.0, qno=1),
        module.QuestionStart(page_index=0, column=1, y0=200.0, qno=2),
    ]
    page_heights = [1000.0]
    page_columns = [[(0.0, 300.0), (320.0, 620.0)]]

    spans = module.build_question_spans(
        starts=starts,
        page_heights=page_heights,
        page_columns=page_columns,
    )

    assert len(spans) == 2
    assert len(spans[0].segments) == 2
    assert spans[0].segments[0].page_index == 0
    assert spans[0].segments[0].column == 0
    assert spans[0].segments[0].start_y == 100.0
    assert spans[0].segments[0].end_y == 1000.0
    assert spans[0].segments[1].column == 1
    assert spans[0].segments[1].start_y == 0.0
    assert spans[0].segments[1].end_y == 200.0
    assert len(spans[1].segments) == 1
    assert spans[1].segments[0].column == 1
    assert spans[1].segments[0].start_y == 200.0


def test_refine_clip_y_to_text_blocks_trims_non_text_lines():
    module = load_module()
    y0, y1 = module.refine_clip_y_to_text_blocks(
        raw_y0=100.0,
        raw_y1=400.0,
        text_block_boxes=[
            (50.0, 130.0, 250.0, 180.0),
            (60.0, 220.0, 260.0, 310.0),
        ],
    )
    assert y0 >= 120.0
    assert y1 <= 320.0


def test_refine_clip_y_to_text_blocks_fallback_when_no_text():
    module = load_module()
    y0, y1 = module.refine_clip_y_to_text_blocks(
        raw_y0=100.0,
        raw_y1=400.0,
        text_block_boxes=[],
    )
    assert y0 == 100.0
    assert y1 == 400.0


def test_normalize_two_columns_removes_overlap():
    module = load_module()
    cols = module.normalize_two_columns([(40.0, 300.0), (260.0, 550.0)])
    assert len(cols) == 2
    assert cols[0][1] < cols[1][0]


def test_refine_clip_x_to_text_blocks_trims_side_noise():
    module = load_module()
    x0, x1 = module.refine_clip_x_to_text_blocks(
        raw_x0=250.0,
        raw_x1=550.0,
        text_block_boxes=[
            (300.0, 120.0, 520.0, 180.0),
            (310.0, 220.0, 530.0, 300.0),
        ],
    )
    assert x0 >= 295.0
    assert x1 <= 535.0


def test_compute_raw_clip_bounds_trims_footer_for_end_of_page_segment():
    module = load_module()
    y0, y1 = module.compute_raw_clip_bounds(
        segment_start_y=100.0,
        segment_end_y=1000.0,
        page_height=1000.0,
        part_index=1,
        top_padding=1.0,
        boundary_gap=2.0,
        footer_margin=70.0,
    )
    assert y0 == 101.0
    assert y1 == 930.0


def test_compute_raw_clip_bounds_first_part_does_not_go_above_start():
    module = load_module()
    y0, y1 = module.compute_raw_clip_bounds(
        segment_start_y=200.0,
        segment_end_y=500.0,
        page_height=1000.0,
        part_index=1,
        top_padding=5.0,
        boundary_gap=2.0,
        footer_margin=70.0,
    )
    assert y0 == 201.0
    assert y1 == 498.0
