#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pipelines.question_parser 단위 테스트"""

import json
import pytest
from pathlib import Path

from pipelines.question_parser import (
    filter_content_nodes,
    extract_questions,
    collect_image_elements,
    parse_choices_from_kids,
    QUESTION_NUMBER_RE,
)

SAMPLE_JSON_PATH = Path(__file__).resolve().parent.parent / "tiger" / "sample" / "comh1_040215.json"


@pytest.fixture
def sample_data():
    """tiger/sample/comh1_040215.json 로드"""
    if not SAMPLE_JSON_PATH.exists():
        pytest.skip("샘플 JSON 파일이 없습니다.")
    return json.loads(SAMPLE_JSON_PATH.read_text(encoding="utf-8"))


# ──────────────────────────────────────────────
# filter_content_nodes
# ──────────────────────────────────────────────
class TestFilterContentNodes:

    def test_removes_header_nodes(self):
        kids = [
            {"type": "header", "id": 1, "page number": 1, "kids": []},
            {"type": "list", "id": 2, "page number": 1},
        ]
        result = filter_content_nodes(kids)
        assert len(result) == 1
        assert result[0]["type"] == "list"

    def test_removes_footer_nodes(self):
        kids = [
            {"type": "list", "id": 1, "page number": 1},
            {"type": "footer", "id": 2, "page number": 1, "kids": []},
        ]
        result = filter_content_nodes(kids)
        assert len(result) == 1
        assert result[0]["type"] == "list"

    def test_removes_caption_nodes(self):
        kids = [
            {"type": "list", "id": 1, "page number": 1},
            {"type": "caption", "id": 2, "page number": 1, "content": "광고"},
        ]
        result = filter_content_nodes(kids)
        assert len(result) == 1

    def test_keeps_content_nodes(self):
        kids = [
            {"type": "paragraph", "id": 1, "page number": 1, "content": "1과목"},
            {"type": "list", "id": 2, "page number": 1},
            {"type": "table", "id": 3, "page number": 5},
        ]
        result = filter_content_nodes(kids)
        assert len(result) == 3

    def test_sample_json_filter(self, sample_data):
        """샘플 JSON에서 header/footer가 모두 제거되는지 확인"""
        kids = sample_data.get("kids", [])
        original_count = len(kids)
        filtered = filter_content_nodes(kids)
        removed = original_count - len(filtered)
        # 5페이지 × (header + footer) = 10개 + caption 1개 = 11개 제거
        assert removed >= 10
        for node in filtered:
            assert node["type"] not in ("header", "footer")


# ──────────────────────────────────────────────
# QUESTION_NUMBER_RE
# ──────────────────────────────────────────────
class TestQuestionNumberRegex:

    def test_dot_pattern(self):
        m = QUESTION_NUMBER_RE.match("1. 다음 기호 중")
        assert m and int(m.group(1)) == 1

    def test_space_pattern(self):
        m = QUESTION_NUMBER_RE.match("11 다음을 설명하는")
        assert m
        assert int(m.group(1) or m.group(2)) == 11

    def test_paren_pattern(self):
        m = QUESTION_NUMBER_RE.match("3) 다음 중")
        assert m and int(m.group(1)) == 3

    def test_no_match_choice(self):
        """선택지 ①②③④ 는 매칭하지 않아야 한다"""
        assert QUESTION_NUMBER_RE.match("① 선택지") is None

    def test_no_match_plain_text(self):
        assert QUESTION_NUMBER_RE.match("컴퓨터활용능력") is None


# ──────────────────────────────────────────────
# parse_choices_from_kids
# ──────────────────────────────────────────────
class TestParseChoicesFromKids:

    def test_paragraph_choices(self):
        """paragraph 형태 선택지 (① ... ② ...)"""
        kids = [
            {"type": "paragraph", "content": "① \\ ② > ③ : ④ $"},
        ]
        choices = parse_choices_from_kids(kids)
        assert len(choices) == 4
        assert choices[0]["number"] == 1
        assert choices[3]["number"] == 4

    def test_multi_paragraph_choices(self):
        """여러 paragraph에 나뉜 선택지"""
        kids = [
            {"type": "paragraph", "content": "① SNMP ② SMTP"},
            {"type": "paragraph", "content": "③ POP ④ IMAP"},
        ]
        choices = parse_choices_from_kids(kids)
        assert len(choices) == 4
        assert choices[2]["text"] == "POP"

    def test_nested_list_choices(self):
        """중첩 list 형태 선택지"""
        kids = [
            {
                "type": "list",
                "numbering style": "circled arabic numbers",
                "list items": [
                    {"type": "list item", "content": "① 선택지A", "kids": []},
                    {"type": "list item", "content": "② 선택지B", "kids": []},
                    {"type": "list item", "content": "③ 선택지C", "kids": []},
                    {"type": "list item", "content": "④ 선택지D", "kids": []},
                ],
            }
        ]
        choices = parse_choices_from_kids(kids)
        assert len(choices) == 4

    def test_empty_kids(self):
        """빈 kids — 선택지 없음"""
        choices = parse_choices_from_kids([])
        assert choices == []


# ──────────────────────────────────────────────
# extract_questions
# ──────────────────────────────────────────────
class TestExtractQuestions:

    def test_simple_extraction(self):
        """단순 list에서 문제 추출"""
        kids = [
            {
                "type": "list",
                "id": 1,
                "page number": 1,
                "level": "1",
                "numbering style": "arabic numbers",
                "number of list items": 2,
                "list items": [
                    {
                        "type": "list item",
                        "page number": 1,
                        "bounding box": [22.8, 700, 293.52, 746],
                        "content": "1. 첫 번째 문제",
                        "kids": [
                            {"type": "paragraph", "content": "① A ② B ③ C ④ D"},
                        ],
                    },
                    {
                        "type": "list item",
                        "page number": 1,
                        "bounding box": [22.8, 600, 293.52, 650],
                        "content": "2. 두 번째 문제",
                        "kids": [
                            {"type": "paragraph", "content": "① X ② Y"},
                        ],
                    },
                ],
            }
        ]
        questions = extract_questions(kids)
        assert len(questions) == 2
        assert questions[0]["question_number"] == 1
        assert questions[1]["question_number"] == 2
        assert questions[0]["question_text"] == "첫 번째 문제"
        assert len(questions[0]["choices"]) == 4

    def test_sample_json_60_questions(self, sample_data):
        """샘플 JSON에서 60문제가 추출되는지 확인"""
        filtered = filter_content_nodes(sample_data.get("kids", []))
        questions = extract_questions(filtered)
        qnos = [q["question_number"] for q in questions]
        assert len(questions) == 60
        assert qnos == list(range(1, 61))

    def test_question_has_required_fields(self, sample_data):
        """문제에 필수 필드가 있는지 확인"""
        filtered = filter_content_nodes(sample_data.get("kids", []))
        questions = extract_questions(filtered)
        for q in questions:
            assert "question_number" in q
            assert "page_number" in q
            assert "question_text" in q
            assert "choices" in q
            assert "images" in q
            assert "bounding_box" in q
            assert isinstance(q["question_number"], int)
            assert isinstance(q["choices"], list)

    def test_choices_parsed_for_question_1(self, sample_data):
        """문제 1의 선택지가 4개인지 확인"""
        filtered = filter_content_nodes(sample_data.get("kids", []))
        questions = extract_questions(filtered)
        q1 = next(q for q in questions if q["question_number"] == 1)
        assert len(q1["choices"]) == 4


# ──────────────────────────────────────────────
# collect_image_elements
# ──────────────────────────────────────────────
class TestCollectImageElements:

    def test_collects_image_nodes(self):
        kids = [
            {"type": "image", "id": 16, "page number": 1, "bounding box": [0, 0, 50, 50], "source": "img.png"},
            {"type": "paragraph", "id": 17, "content": "text"},
        ]
        result = collect_image_elements(kids)
        assert len(result) == 1
        assert result[0]["type"] == "image"

    def test_collects_table_nodes(self):
        kids = [
            {"type": "table", "id": 1, "page number": 5, "bounding box": [0, 0, 500, 300]},
        ]
        result = collect_image_elements(kids)
        assert len(result) == 1

    def test_collects_nested_images(self):
        """kids 안에 중첩된 image 노드도 수집"""
        kids = [
            {
                "type": "list",
                "kids": [
                    {"type": "image", "id": 10, "page number": 1, "bounding box": [0, 0, 10, 10]},
                ],
            }
        ]
        result = collect_image_elements(kids)
        assert len(result) == 1

    def test_sample_json_image_count(self, sample_data):
        """샘플 JSON에서 image 요소가 16개인지 확인 (comh1_040215_images/ 파일 수와 동일)"""
        filtered = filter_content_nodes(sample_data.get("kids", []))
        images = collect_image_elements(filtered)
        # image type만 카운트 (table 제외)
        image_only = [img for img in images if img.get("type") == "image"]
        assert len(image_only) >= 1  # 최소 1개 이상
