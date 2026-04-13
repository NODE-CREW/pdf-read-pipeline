#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EasyOCR 통합 테스트."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipelines.base import (
    _get_easyocr_reader,
    _ocr_with_easyocr,
    _ocr_with_tesseract,
    ocr_text_from_image_paths,
)


class TestGetEasyOCRReader:
    """_get_easyocr_reader 함수 테스트."""

    def test_returns_none_when_import_fails(self):
        """EasyOCR import 실패 시 None 반환."""
        import pipelines.base as base_module
        
        # 상태 초기화
        base_module._EASYOCR_READER = None
        base_module._EASYOCR_AVAILABLE = None
        
        with patch.dict("sys.modules", {"easyocr": None}):
            with patch("builtins.__import__", side_effect=ImportError("No module")):
                result = _get_easyocr_reader()
                assert result is None
                assert base_module._EASYOCR_AVAILABLE is False

    def test_returns_cached_instance(self):
        """캐시된 인스턴스 반환 테스트."""
        import pipelines.base as base_module
        
        mock_reader = MagicMock()
        base_module._EASYOCR_READER = mock_reader
        base_module._EASYOCR_AVAILABLE = True
        
        result = _get_easyocr_reader()
        assert result is mock_reader
        
        # cleanup
        base_module._EASYOCR_READER = None
        base_module._EASYOCR_AVAILABLE = None


class TestOcrWithEasyOCR:
    """_ocr_with_easyocr 함수 테스트."""

    def test_returns_empty_when_easyocr_unavailable(self):
        """EasyOCR 사용 불가 시 빈 문자열 반환."""
        import pipelines.base as base_module
        
        base_module._EASYOCR_AVAILABLE = False
        base_module._EASYOCR_READER = None
        
        result = _ocr_with_easyocr("/fake/path.png")
        assert result == ""
        
        # cleanup
        base_module._EASYOCR_AVAILABLE = None

    def test_extracts_text_from_ocr_result(self):
        """OCR 결과에서 텍스트 추출 테스트."""
        import pipelines.base as base_module
        
        mock_reader = MagicMock()
        mock_reader.readtext.return_value = ["첫 번째 줄", "두 번째 줄"]
        
        base_module._EASYOCR_READER = mock_reader
        base_module._EASYOCR_AVAILABLE = True
        
        result = _ocr_with_easyocr("/fake/path.png")
        assert "첫 번째 줄" in result
        assert "두 번째 줄" in result
        
        # cleanup
        base_module._EASYOCR_READER = None
        base_module._EASYOCR_AVAILABLE = None


class TestOcrTextFromImagePaths:
    """ocr_text_from_image_paths 함수 테스트."""

    def test_uses_easyocr_first_when_enabled(self):
        """use_easyocr=True일 때 EasyOCR 우선 사용."""
        import pipelines.base as base_module
        
        with patch.object(base_module, "_ocr_with_easyocr", return_value="easyocr result") as mock_easy:
            with patch.object(base_module, "_ocr_with_tesseract", return_value="tesseract result") as mock_tess:
                result = ocr_text_from_image_paths(["/fake/path.png"], use_easyocr=True)
                
                mock_easy.assert_called_once()
                mock_tess.assert_not_called()
                assert result == "easyocr result"

    def test_falls_back_to_tesseract_when_easyocr_fails(self):
        """EasyOCR 실패 시 Tesseract fallback."""
        import pipelines.base as base_module
        
        with patch.object(base_module, "_ocr_with_easyocr", return_value="") as mock_easy:
            with patch.object(base_module, "_ocr_with_tesseract", return_value="tesseract result") as mock_tess:
                result = ocr_text_from_image_paths(["/fake/path.png"], use_easyocr=True)
                
                mock_easy.assert_called_once()
                mock_tess.assert_called_once()
                assert result == "tesseract result"

    def test_skips_easyocr_when_disabled(self):
        """use_easyocr=False일 때 Tesseract만 사용."""
        import pipelines.base as base_module
        
        with patch.object(base_module, "_ocr_with_easyocr", return_value="easyocr result") as mock_easy:
            with patch.object(base_module, "_ocr_with_tesseract", return_value="tesseract result") as mock_tess:
                result = ocr_text_from_image_paths(["/fake/path.png"], use_easyocr=False)
                
                mock_easy.assert_not_called()
                mock_tess.assert_called_once()
                assert result == "tesseract result"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
