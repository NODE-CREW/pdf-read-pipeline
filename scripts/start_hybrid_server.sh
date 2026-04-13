#!/bin/bash
# Hybrid OCR 서버 시작 스크립트
# 한국어 OCR 강제 적용이 기본값

PORT=${1:-5002}

echo "Starting hybrid server on port $PORT with Korean OCR enabled..."
opendataloader-pdf-hybrid --port "$PORT" --force-ocr --ocr-lang ko
