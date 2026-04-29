from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from new.test1_parser import (
    clean_tree_crop_image,
    extract_ordered_lines,
    get_non_edge_content_bbox,
    parse_choice_text,
    parse_test1_pdf,
    remove_edge_vertical_noise,
)


TEST1_PDF_PATH = Path(__file__).resolve().parent.parent / "data" / "test-1.pdf"


def test_parse_choice_text_splits_four_choices():
    question_text, choices = parse_choice_text(
        "객체지향 분석 방법론 중 구성되는 것은? ① Coad 와 Yourdon 방법 ② Booch 방법 ③ Jacobson 방법 ④ Wirfs-Brocks 방법"
    )

    assert question_text == "객체지향 분석 방법론 중 구성되는 것은?"
    assert [choice["number"] for choice in choices] == [1, 2, 3, 4]
    assert choices[0]["text"] == "Coad 와 Yourdon 방법"
    assert choices[3]["text"] == "Wirfs-Brocks 방법"


def test_remove_edge_vertical_noise_drops_border_separator_only():
    image = Image.new("L", (80, 80), 255)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 4, 79), fill=0)
    draw.rectangle((20, 10, 60, 60), fill=0)

    cleaned = remove_edge_vertical_noise(image)
    dark_bbox = cleaned.point(lambda pixel: 255 if pixel > 0 else 0).point(
        lambda pixel: 0 if pixel == 255 else 255
    ).getbbox()

    assert dark_bbox == (20, 10, 61, 61)


def test_get_non_edge_content_bbox_prefers_internal_component_over_edge_noise():
    image = Image.new("L", (100, 80), 255)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 30, 79), fill=0)
    draw.rectangle((40, 8, 90, 70), fill=0)

    bbox = get_non_edge_content_bbox(image)

    assert bbox == (40, 8, 91, 71)


def test_clean_tree_crop_image_whitens_edge_connected_noise():
    image = Image.new("RGB", (80, 80), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 20, 30), fill=(180, 180, 180))
    draw.line((25, 10, 55, 10), fill=(0, 0, 0), width=2)
    draw.line((40, 10, 30, 30), fill=(0, 0, 0), width=2)
    draw.line((40, 10, 50, 30), fill=(0, 0, 0), width=2)

    cleaned = clean_tree_crop_image(image, threshold=245).convert("L")

    assert cleaned.getpixel((5, 5)) == 255
    assert cleaned.getpixel((40, 10)) < 245


@pytest.mark.skipif(not TEST1_PDF_PATH.exists(), reason="test-1 PDF 파일이 없습니다.")
def test_parse_test1_pdf_builds_output_schema_and_crops(tmp_path):
    result = parse_test1_pdf(TEST1_PDF_PATH, out_dir=tmp_path)

    assert set(result.keys()) == {"source", "questions", "image_crops", "metadata"}
    assert result["source"] == "test-1.pdf"
    assert result["metadata"]["total_questions"] == 100

    questions = result["questions"]
    assert [question["question_number"] for question in questions] == list(range(1, 101))

    q1 = questions[0]
    q100 = questions[-1]
    assert q1["page_number"] == 1
    assert q1["question_text"].startswith("객체지향 분석 방법론 중")
    assert "E-R" in q1["question_text"]
    assert "1 회" not in q1["question_text"]
    assert len(q1["choices"]) == 4
    assert q1["choices"][0]["text"].startswith("Coad")

    assert q100["page_number"] == 7
    assert result["metadata"]["pages"] == q100["page_number"] + 1
    assert q100["question_text"].endswith("표준은?")
    assert len(q100["choices"]) == 4
    assert q100["choices"][3]["text"] == "SPICE"

    assert result["image_crops"]
    first_crop = result["image_crops"][0]
    assert first_crop["crop_path"].startswith("crops/")
    assert (tmp_path / first_crop["crop_path"]).exists()


@pytest.mark.skipif(not TEST1_PDF_PATH.exists(), reason="test-1 PDF 파일이 없습니다.")
def test_parse_test1_pdf_filters_text_only_crops_and_keeps_visual_ones(tmp_path):
    result = parse_test1_pdf(TEST1_PDF_PATH, out_dir=tmp_path)

    by_number = {question["question_number"]: question for question in result["questions"]}

    assert len(by_number[23]["images"]) == 1
    assert len(by_number[28]["images"]) == 1
    assert len(by_number[51]["images"]) == 1
    assert len(by_number[66]["images"]) == 1
    assert len(by_number[89]["images"]) == 1
    assert len(by_number[14]["images"]) == 1
    assert len(by_number[24]["images"]) == 1
    assert len(by_number[26]["images"]) == 1
    assert len(by_number[67]["images"]) == 1
    assert len(by_number[69]["images"]) == 1
    assert len(by_number[97]["images"]) == 1

    assert "디자인" not in by_number[14]["question_text"]
    assert "JavaScript" not in by_number[24]["question_text"]
    assert "37, 14, 17, 40, 35" not in by_number[26]["question_text"]
    assert "while (y--)" not in by_number[67]["question_text"]
    assert "System.out.print" not in by_number[69]["question_text"]
    assert "광채널 스위치" not in by_number[97]["question_text"]

    for image in (
        by_number[14]["images"]
        + by_number[24]["images"]
        + by_number[26]["images"]
        + by_number[23]["images"]
        + by_number[28]["images"]
        + by_number[51]["images"]
        + by_number[66]["images"]
        + by_number[67]["images"]
        + by_number[69]["images"]
        + by_number[89]["images"]
        + by_number[97]["images"]
    ):
        assert (tmp_path / image["crop_path"]).exists()


@pytest.mark.skipif(not TEST1_PDF_PATH.exists(), reason="test-1 PDF 파일이 없습니다.")
def test_parse_test1_pdf_uses_unique_crop_paths_per_question(tmp_path):
    result = parse_test1_pdf(TEST1_PDF_PATH, out_dir=tmp_path)

    by_number = {question["question_number"]: question for question in result["questions"]}
    q14_path = by_number[14]["images"][0]["crop_path"]
    q23_path = by_number[23]["images"][0]["crop_path"]

    assert q14_path != q23_path
    assert (tmp_path / q14_path).exists()
    assert (tmp_path / q23_path).exists()


@pytest.mark.skipif(not TEST1_PDF_PATH.exists(), reason="test-1 PDF 파일이 없습니다.")
def test_parse_test1_pdf_crops_q23_q28_tree_only_region(tmp_path):
    result = parse_test1_pdf(TEST1_PDF_PATH, out_dir=tmp_path)
    by_number = {question["question_number"]: question for question in result["questions"]}

    import fitz

    doc = fitz.open(TEST1_PDF_PATH)
    try:
        lines = extract_ordered_lines(doc)
    finally:
        doc.close()

    for question_number in [23, 28]:
        crop_bbox = by_number[question_number]["images"][0]["bounding_box"]
        question_lines = []
        collecting = False
        for line in lines:
            import re

            match = re.match(r"^(\d{1,3})\.\s*(.*)$", line.text)
            if match and int(match.group(1)) == question_number:
                collecting = True
            elif match and collecting:
                break
            if collecting:
                question_lines.append(line)

        stem_bottom = question_lines[0].bbox[3]
        first_choice_top = next(line.bbox[1] for line in question_lines if line.text.startswith("①"))

        assert crop_bbox[1] > stem_bottom
        assert crop_bbox[3] < first_choice_top

    q28_crop_bbox = by_number[28]["images"][0]["bounding_box"]
    q28_question_bbox = by_number[28]["bounding_box"]
    assert q28_crop_bbox[1] > q28_question_bbox[1]
