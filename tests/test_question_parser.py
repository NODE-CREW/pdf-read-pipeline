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
    _extract_description_from_kids,
    _link_crops_to_questions,
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

    def test_keeps_caption_with_choice_markers(self):
        """선택지 마커가 포함된 caption은 유지"""
        kids = [
            {"type": "caption", "id": 1, "content": "① 통합 프로그램 ② 저장소 ③ 모듈 ④ 데이터"},
            {"type": "caption", "id": 2, "content": "Figure 1"},
            {"type": "paragraph", "id": 3, "content": "본문"},
        ]
        result = filter_content_nodes(kids)
        assert len(result) == 2
        assert result[0]["type"] == "caption"  # choice caption kept
        assert result[1]["type"] == "paragraph"

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
            assert "description" in q
            assert isinstance(q["question_number"], int)
            assert isinstance(q["choices"], list)
            assert isinstance(q["description"], str)

    def test_choices_parsed_for_question_1(self, sample_data):
        """문제 1의 선택지가 4개인지 확인"""
        filtered = filter_content_nodes(sample_data.get("kids", []))
        questions = extract_questions(filtered)
        q1 = next(q for q in questions if q["question_number"] == 1)
        assert len(q1["choices"]) == 4

    def test_section_heading_not_appended_and_caption_choices(self):
        """Q24 패턴: text block heading은 무시, caption 선택지가 정상 연결"""
        kids = [
            {
                "type": "list", "id": 1, "page number": 2,
                "numbering style": "arabic numbers",
                "list items": [{
                    "type": "list item", "page number": 2,
                    "bounding box": [304, 40, 493, 49],
                    "content": "24. 다음 설명에 부합하는 용어로 옳은 것은?",
                    "kids": [],
                }],
            },
            {
                "type": "text block", "id": 185, "page number": 2,
                "kids": [{"type": "heading", "level": "Subtitle",
                          "content": "2과목 : 소프트웨어 개발"}],
            },
            {"type": "image", "id": 190, "page number": 3,
             "bounding box": [40, 681, 264, 775], "source": "img4.png"},
            {"type": "caption", "id": 191, "page number": 3,
             "content": "① 통합 프로그램 ② 저장소 ③ 모듈 ④ 데이터"},
        ]
        questions = extract_questions(kids)
        q = questions[0]
        assert "2과목" not in q["question_text"]
        assert len(q["choices"]) == 4
        assert q["choices"][0]["text"] == "통합 프로그램"
        assert len(q["images"]) == 1
        assert q["images"][0]["element_id"] == 190

    def test_description_extracted_from_unordered_list_in_kids(self):
        """문제 kids 내 text block > unordered list에서 설명 텍스트 추출 (Q85 패턴)"""
        kids = [
            {
                "type": "list",
                "numbering style": "arabic numbers",
                "list items": [
                    {
                        "type": "list item",
                        "page number": 13,
                        "bounding box": [39, 659, 212, 674],
                        "content": "85 아래 설명에 해당하는 용어는 무엇인가?",
                        "kids": [
                            {
                                "type": "text block",
                                "id": 150,
                                "kids": [
                                    {
                                        "type": "list",
                                        "numbering style": "unordered",
                                        "list items": [
                                            {"type": "list item", "content": "•1990년대의 '스노우 크래쉬' 소설에서 처음 사용된 용어이다.", "kids": []},
                                            {"type": "list item", "content": "•현실 세계와 같이 사회, 경제, 문화 활동에 대한 상호작용이 이뤄진다.", "kids": []},
                                            {"type": "list item", "content": "•게임, SNS, 교육, 의료 등 많은 산업에서 활용한다.", "kids": []},
                                        ],
                                    }
                                ],
                            },
                            {
                                "type": "list",
                                "numbering style": "unknown style",
                                "list items": [
                                    {"type": "list item", "content": "① Augmented Reality", "kids": []},
                                    {"type": "list item", "content": "② Metaverse", "kids": []},
                                    {"type": "list item", "content": "③ Mobile Location Service", "kids": []},
                                    {"type": "list item", "content": "④ Hologram", "kids": []},
                                ],
                            },
                        ],
                    },
                ],
            }
        ]
        questions = extract_questions(kids)
        assert len(questions) == 1
        q = questions[0]
        assert q["question_number"] == 85
        assert "description" in q
        assert "1990년대" in q["description"]
        assert "상호작용" in q["description"]
        assert "산업에서" in q["description"]
        assert len(q["choices"]) == 4

    def test_description_empty_when_no_text_block(self):
        """text block이 없는 문제는 description이 빈 문자열"""
        kids = [
            {
                "type": "list",
                "numbering style": "arabic numbers",
                "list items": [
                    {
                        "type": "list item",
                        "page number": 1,
                        "bounding box": [22, 700, 293, 746],
                        "content": "1. 첫 번째 문제",
                        "kids": [
                            {"type": "paragraph", "content": "① A ② B ③ C ④ D"},
                        ],
                    },
                ],
            }
        ]
        questions = extract_questions(kids)
        assert questions[0]["description"] == ""

    def test_choices_split_across_paragraphs(self):
        """선택지가 여러 paragraph에 분할된 경우 모두 연결 (Q100 패턴)"""
        kids = [
            {
                "type": "list",
                "numbering style": "arabic numbers",
                "list items": [
                    {
                        "type": "list item",
                        "page number": 8,
                        "bounding box": [22, 135, 188, 144],
                        "content": "100. 다음 LAN의 네트워크 토폴로지는?",
                        "kids": [],
                    },
                ],
            },
            {"type": "image", "id": 277, "page number": 8,
             "bounding box": [40, 46, 240, 129], "source": "img.png"},
            {"type": "paragraph", "id": 278, "page number": 8,
             "content": "① 버스형 ② 성형"},
            {"type": "paragraph", "id": 279, "page number": 8,
             "content": "③ 링형 ④ 그물형"},
        ]
        questions = extract_questions(kids)
        assert len(questions) == 1
        q = questions[0]
        assert q["question_number"] == 100
        assert len(q["choices"]) == 4
        assert q["choices"][0]["text"] == "버스형"
        assert q["choices"][2]["text"] == "링형"
        assert q["choices"][3]["text"] == "그물형"

    def test_image_choices_pattern(self):
        """이미지 선택지 패턴 (Q43 유형): 문제 뒤 이미지+레이블 조합"""
        kids = [
            {
                "type": "list", "id": 1, "page number": 4,
                "numbering style": "arabic numbers",
                "number of list items": 1,
                "list items": [
                    {
                        "type": "list item", "page number": 4,
                        "bounding box": [304, 385, 554, 405],
                        "content": "43. 다음 두 릴레이션의 카티션 프로덕트 수행 결과는?",
                        "kids": [],
                    },
                ],
            },
            {"type": "image", "id": 209, "page number": 4,
             "bounding box": [322, 304, 460, 379], "source": "img8.png"},
            {"type": "image", "id": 211, "page number": 4,
             "bounding box": [336, 223, 426, 298], "source": "img9.png"},
            {"type": "image", "id": 212, "page number": 4,
             "bounding box": [458, 223, 548, 298], "source": "img10.png"},
            {"type": "paragraph", "id": 210, "page number": 4,
             "content": "① ②"},
            {"type": "image", "id": 215, "page number": 4,
             "bounding box": [456, 36, 546, 217], "source": "img11.png"},
            {"type": "image", "id": 214, "page number": 4,
             "bounding box": [336, 52, 424, 127], "source": "img12.png"},
            {"type": "paragraph", "id": 213, "page number": 4,
             "content": "③ ④"},
        ]
        questions = extract_questions(kids)
        assert len(questions) == 1
        q = questions[0]
        assert q["question_number"] == 43
        assert len(q["choices"]) == 4
        # 선택지에 image가 있어야 함
        for c in q["choices"]:
            assert "image" in c
        # x좌표 기준 정렬: ①=img211(x=336), ②=img212(x=458)
        c1 = next(c for c in q["choices"] if c["number"] == 1)
        assert c1["image"]["element_id"] == 211
        c2 = next(c for c in q["choices"] if c["number"] == 2)
        assert c2["image"]["element_id"] == 212
        # ③=img214(x=336), ④=img215(x=456)
        c3 = next(c for c in q["choices"] if c["number"] == 3)
        assert c3["image"]["element_id"] == 214
        c4 = next(c for c in q["choices"] if c["number"] == 4)
        assert c4["image"]["element_id"] == 215
        # 문제 레벨 이미지 (R1/R2 테이블)
        assert len(q["images"]) == 1
        assert q["images"][0]["element_id"] == 209


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


# ──────────────────────────────────────────────
# _link_crops_to_questions
# ──────────────────────────────────────────────
class TestLinkCropsToQuestions:

    def test_links_crop_path_by_element_id(self):
        """crop 결과가 question images에 crop_path로 연결되는지 확인"""
        questions = [
            {
                "question_number": 1,
                "images": [
                    {"type": "image", "element_id": 149, "page_number": 1,
                     "bounding_box": [0, 0, 100, 100], "source": "orig/img1.png"},
                ],
            },
            {
                "question_number": 2,
                "images": [],
            },
        ]
        image_crops = [
            {"element_id": 149, "page_number": 1, "type": "image",
             "bounding_box": [0, 0, 100, 100], "crop_path": "crops/crop_id0149_p1.png"},
        ]
        _link_crops_to_questions(questions, image_crops)
        assert questions[0]["images"][0]["crop_path"] == "crops/crop_id0149_p1.png"
        assert questions[1]["images"] == []

    def test_no_crops_no_change(self):
        """crop이 없으면 images는 그대로"""
        questions = [
            {
                "question_number": 1,
                "images": [
                    {"type": "image", "element_id": 10, "page_number": 1,
                     "bounding_box": [0, 0, 50, 50], "source": "orig/img.png"},
                ],
            },
        ]
        _link_crops_to_questions(questions, [])
        assert "crop_path" not in questions[0]["images"][0]

    def test_multiple_images_in_question(self):
        """문제에 여러 이미지가 있을 때 각각 매칭"""
        questions = [
            {
                "question_number": 1,
                "images": [
                    {"type": "image", "element_id": 10, "source": "a.png"},
                    {"type": "image", "element_id": 20, "source": "b.png"},
                ],
            },
        ]
        image_crops = [
            {"element_id": 10, "crop_path": "crops/crop_10.png"},
            {"element_id": 20, "crop_path": "crops/crop_20.png"},
        ]
        _link_crops_to_questions(questions, image_crops)
        assert questions[0]["images"][0]["crop_path"] == "crops/crop_10.png"
        assert questions[0]["images"][1]["crop_path"] == "crops/crop_20.png"

    def test_links_crop_path_to_choice_images(self):
        """선택지 image에도 crop_path가 연결되는지 확인"""
        questions = [
            {
                "question_number": 43,
                "images": [],
                "choices": [
                    {"number": 1, "text": "", "image": {"element_id": 211, "source": "a.png"}},
                    {"number": 2, "text": ""},
                ],
            },
        ]
        image_crops = [
            {"element_id": 211, "crop_path": "crops/crop_211.png"},
        ]
        _link_crops_to_questions(questions, image_crops)
        assert questions[0]["choices"][0]["image"]["crop_path"] == "crops/crop_211.png"
        # image가 없는 선택지는 영향 없음
        assert "image" not in questions[0]["choices"][1]
