#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PDF to Markdown 변환 파이프라인 테스트"""

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from pipelines.pdf_to_markdown import (
    filter_image_elements,
    crop_image_from_bbox,
    generate_image_filename,
    element_to_markdown,
    assemble_markdown,
    split_into_questions,
)


class TestFilterImageElements:
    """JSON 요소에서 이미지 대상 필터링 테스트"""

    def test_filter_table_elements(self):
        """table 타입 요소 필터링"""
        elements = [
            {"type": "table", "id": 1, "bounding box": [0, 0, 100, 100]},
            {"type": "paragraph", "id": 2, "content": "text"},
            {"type": "table", "id": 3, "bounding box": [0, 0, 100, 100]},
        ]
        result = filter_image_elements(elements)
        assert len(result) == 2
        assert all(e["type"] == "table" for e in result)

    def test_filter_picture_elements(self):
        """picture 타입 요소 필터링"""
        elements = [
            {"type": "picture", "id": 1, "bounding box": [0, 0, 100, 100]},
            {"type": "heading", "id": 2, "content": "Title"},
        ]
        result = filter_image_elements(elements)
        assert len(result) == 1
        assert result[0]["type"] == "picture"

    def test_filter_image_elements(self):
        """image 타입 요소 필터링 (이미 추출된 이미지)"""
        elements = [
            {"type": "image", "id": 1, "source": "images/img1.png"},
            {"type": "paragraph", "id": 2, "content": "text"},
        ]
        result = filter_image_elements(elements)
        assert len(result) == 1

    def test_filter_formula_elements(self):
        """formula 타입 요소 필터링"""
        elements = [
            {"type": "formula", "id": 1, "bounding box": [0, 0, 50, 20]},
        ]
        result = filter_image_elements(elements)
        assert len(result) == 1

    def test_empty_elements(self):
        """빈 요소 리스트"""
        result = filter_image_elements([])
        assert result == []


class TestGenerateImageFilename:
    """이미지 파일명 생성 규칙 테스트"""

    def test_table_filename(self):
        """표 이미지 파일명: table_p01_001.png"""
        result = generate_image_filename("table", page=1, index=1)
        assert result == "table_p01_001.png"

    def test_figure_filename(self):
        """그림 이미지 파일명: figure_p02_003.png"""
        result = generate_image_filename("figure", page=2, index=3)
        assert result == "figure_p02_003.png"

    def test_formula_filename(self):
        """수식 이미지 파일명: formula_p05_001.png"""
        result = generate_image_filename("formula", page=5, index=1)
        assert result == "formula_p05_001.png"


class TestCropImageFromBbox:
    """bounding box 기반 이미지 crop 테스트"""

    def test_crop_invalid_bbox(self):
        """잘못된 bbox 처리"""
        bbox = [0, 0, 0, 0]
        result = crop_image_from_bbox(None, 1, bbox)
        assert result is None

    def test_crop_empty_bbox(self):
        """빈 bbox 처리"""
        result = crop_image_from_bbox(None, 1, [])
        assert result is None


class TestElementToMarkdown:
    """요소 타입별 마크다운 변환 테스트"""

    def test_heading_to_markdown(self):
        """heading → # 제목"""
        element = {
            "type": "heading",
            "heading level": 1,
            "content": "1과목. 컴퓨터 일반",
        }
        result = element_to_markdown(element)
        assert result == "# 1과목. 컴퓨터 일반"

    def test_heading_level_2(self):
        """heading level 2 → ## 제목"""
        element = {
            "type": "heading",
            "heading level": 2,
            "content": "문제 1",
        }
        result = element_to_markdown(element)
        assert result == "## 문제 1"

    def test_paragraph_to_markdown(self):
        """paragraph → 텍스트"""
        element = {
            "type": "paragraph",
            "content": "다음 중 옳은 것은?",
        }
        result = element_to_markdown(element)
        assert result == "다음 중 옳은 것은?"

    def test_list_item_to_markdown(self):
        """list item → 마크다운 리스트"""
        element = {
            "type": "list item",
            "content": "① 선택지 1",
        }
        result = element_to_markdown(element)
        assert "① 선택지 1" in result

    def test_table_to_markdown_image(self):
        """table → 이미지 참조"""
        element = {
            "type": "table",
            "id": 1,
            "_image_path": "./images/table_p01_001.png",
        }
        result = element_to_markdown(element)
        assert result == "![표](./images/table_p01_001.png)"

    def test_image_to_markdown(self):
        """image → 이미지 참조"""
        element = {
            "type": "image",
            "source": "comh1_040215_images/imageFile1.png",
            "_image_path": "./images/figure_p01_001.png",
        }
        result = element_to_markdown(element)
        assert "![" in result and ".png)" in result


class TestAssembleMarkdown:
    """마크다운 문서 조립 테스트"""

    def test_assemble_simple_document(self):
        """간단한 문서 조립"""
        elements = [
            {"type": "heading", "heading level": 1, "content": "제목"},
            {"type": "paragraph", "content": "본문 텍스트"},
        ]
        result = assemble_markdown(elements)
        assert "# 제목" in result
        assert "본문 텍스트" in result

    def test_assemble_with_images(self):
        """이미지 포함 문서 조립"""
        elements = [
            {"type": "heading", "heading level": 1, "content": "문제 1"},
            {"type": "paragraph", "content": "다음 표를 보고 답하시오."},
            {"type": "table", "_image_path": "./images/table_p01_001.png"},
        ]
        result = assemble_markdown(elements)
        assert "![표](./images/table_p01_001.png)" in result


class TestSplitIntoQuestions:
    """문항 분리 테스트"""

    def test_split_simple_questions(self):
        """간단한 문항 분리"""
        markdown = """# 제목

- 1. 첫 번째 문제
  ① 선택지 1
  ② 선택지 2

- 2. 두 번째 문제
  ① 선택지 1
  ② 선택지 2
"""
        questions = split_into_questions(markdown)
        assert len(questions) == 2
        assert questions[0].qno == 1
        assert questions[1].qno == 2

    def test_split_no_questions(self):
        """문항 없는 경우"""
        markdown = "# 제목\n\n본문 텍스트"
        questions = split_into_questions(markdown)
        assert len(questions) == 0


class TestIntegration:
    """통합 테스트"""

    @pytest.fixture
    def sample_json_path(self):
        """샘플 JSON 파일 경로"""
        return Path(__file__).parent.parent / "output" / "test_odl" / "comh1_040215.json"

    def test_load_sample_json(self, sample_json_path):
        """샘플 JSON 파일 로드"""
        if not sample_json_path.exists():
            pytest.skip("샘플 JSON 파일이 없습니다. opendataloader-pdf 테스트를 먼저 실행하세요.")
        
        with open(sample_json_path) as f:
            data = json.load(f)
        
        assert "kids" in data
        assert data["number of pages"] == 5
