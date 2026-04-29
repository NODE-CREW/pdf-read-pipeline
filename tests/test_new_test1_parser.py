from pathlib import Path

import pytest

from new.test1_parser import parse_choice_text, parse_test1_pdf


TEST1_PDF_PATH = Path(__file__).resolve().parent.parent / "data" / "test-1.pdf"


def test_parse_choice_text_splits_four_choices():
    question_text, choices = parse_choice_text(
        "객체지향 분석 방법론 중 구성되는 것은? ① Coad 와 Yourdon 방법 ② Booch 방법 ③ Jacobson 방법 ④ Wirfs-Brocks 방법"
    )

    assert question_text == "객체지향 분석 방법론 중 구성되는 것은?"
    assert [choice["number"] for choice in choices] == [1, 2, 3, 4]
    assert choices[0]["text"] == "Coad 와 Yourdon 방법"
    assert choices[3]["text"] == "Wirfs-Brocks 방법"


@pytest.mark.skipif(not TEST1_PDF_PATH.exists(), reason="test-1 PDF 파일이 없습니다.")
def test_parse_test1_pdf_builds_output_schema_and_crops(tmp_path):
    result = parse_test1_pdf(TEST1_PDF_PATH, out_dir=tmp_path)

    assert set(result.keys()) == {"source", "questions", "image_crops", "metadata"}
    assert result["source"] == "test-1.pdf"
    assert result["metadata"]["total_questions"] == 100
    assert result["metadata"]["pages"] == 8

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
