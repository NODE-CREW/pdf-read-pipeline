from pathlib import Path

import pytest

from pipelines.exam_pdf import parse_exam_pdf


SAMPLE_PDF_PATH = Path(__file__).resolve().parent.parent / "tiger" / "sample" / "comh1_040215.pdf"
TEST1_PDF_PATH = Path(__file__).resolve().parent.parent / "data" / "test-1.pdf"


@pytest.mark.skipif(not SAMPLE_PDF_PATH.exists(), reason="샘플 PDF 파일이 없습니다.")
def test_parse_exam_pdf_parses_sample_exam_end_to_end():
    result = parse_exam_pdf(SAMPLE_PDF_PATH)

    assert result["metadata"]["total_questions"] == 60
    assert result["metadata"]["answer_count"] >= 60

    questions = result["questions"]
    q1 = questions[0]
    q60 = questions[-1]

    assert [question["question_no"] for question in questions] == list(range(1, 61))
    assert "컴퓨터활용능력 1급 필기 기출문제" in result["exam"]["title"]
    assert q1["subject"] == "컴퓨터일반"
    assert q1["stem"].startswith("다음 기호 중 파일명으로 사용할 수 있는 기호는?")
    assert len(q1["choices"]) == 4
    assert q1["answer"] == "④"
    assert q60["question_no"] == 60
    assert len(q60["choices"]) == 4
    assert q60["answer"] == "①"


@pytest.mark.skipif(not SAMPLE_PDF_PATH.exists(), reason="샘플 PDF 파일이 없습니다.")
def test_parse_exam_pdf_writes_question_crop_assets(tmp_path):
    result = parse_exam_pdf(SAMPLE_PDF_PATH, out_dir=tmp_path)

    q1 = result["questions"][0]
    assert q1["assets"]

    first_asset = q1["assets"][0]
    assert first_asset["type"] == "question_crop"
    assert first_asset["path"].startswith("assets/")
    assert (tmp_path / first_asset["path"]).exists()


@pytest.mark.skipif(not TEST1_PDF_PATH.exists(), reason="test-1 PDF 파일이 없습니다.")
def test_parse_exam_pdf_handles_test1_exam_layout(tmp_path):
    result = parse_exam_pdf(TEST1_PDF_PATH, out_dir=tmp_path)

    assert result["metadata"]["total_questions"] == 100
    assert result["metadata"]["answer_count"] == 100

    questions = result["questions"]
    assert [question["question_no"] for question in questions] == list(range(1, 101))

    q1 = questions[0]
    q100 = questions[-1]

    assert q1["subject"] == "소프트웨어 설계"
    assert q1["stem"].startswith("E-R 객체지향 분석 방법론")
    assert len(q1["choices"]) == 4
    assert q1["answer"] == "①"

    assert q100["question_no"] == 100
    assert q100["subject"] == "정보시스템 구축 관리"
    assert q100["answer"] == "④"
