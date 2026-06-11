# PDF Reader

시험지 PDF에서 문제, 선지, 이미지, 해설 보강 정보를 추출해 최종 JSON으로 만드는
파이프라인입니다.

## 현재 구조

- `final/`: 최종 JSON 생성 파이프라인과 AI 보강 로직
- `pipelines/`: PDF/OCR/문항 파싱 공용 로직
- `tests/`: 현재 유지되는 `final/` 및 `pipelines/` 경로의 회귀 테스트
- `scripts/`: 반복 실행용 개발 스크립트
- `docs/`, `doc/`: 설계 메모와 작업 기록

과거 루트의 번호 기반 실험 스크립트는 제거했습니다. 공식 진입점은
`final/parse_pdf.py`입니다.

## 빠른 실행

시나공 형식 PDF를 최종 JSON으로 변환:

```bash
python3 final/parse_pdf.py \
  --pdf ./data/test-1.pdf \
  --output-dir ./final/output/test-1 \
  --parser sinagong
```

일반 PDF 파서를 사용:

```bash
python3 final/parse_pdf.py \
  --pdf ./data/sample.pdf \
  --output-dir ./final/output/sample \
  --parser normal
```

AI 보강 없이 로컬 파서 결과만 확인하려면 `--ai-base-url`을 생략합니다. OpenAI-compatible
endpoint를 붙일 때의 상세 옵션은 [`final/README.md`](final/README.md)를 참고합니다.

## 출력 구조

```text
final/output/<pdf-name>/
  questions_final.json
  images/
    image001.png
    image002.png
```

`questions_final.json`은 문제 본문, 문제 출처, 이미지, 힌트 해설, 선지, 선지별 해설,
정답 여부, 검수 필요 여부 메타데이터를 포함합니다.

## 개발 및 테스트

의존성 설치:

```bash
python3 -m pip install -r requirements.txt
```

핵심 테스트:

```bash
python3 -m pytest tests/test_final_pipeline.py
python3 -m pytest tests/test_pipeline_package_layout.py tests/test_question_parser.py tests/test_pdf_to_markdown.py
```

가능하면 전체 테스트도 실행합니다.

```bash
python3 -m pytest
```

## Legacy 제거 기록

다음 파일/폴더 계열은 유지 대상이 아니어서 제거했습니다.

- 루트 번호 기반 실험 스크립트: `1_...`부터 `11_...`, `6-1`, `6_2`, `8-2` 등
- 루트 임시/디버그 파일: `_debug_json.py`, `ngrok_test*`, `read_text_pdf.py`,
  `read_mixed_text_pdf.py`, `tmp_*.png`, `problem-*.png`, `test.png`, `memo.md`
- 과거 복사본/실험 폴더: `new/`, `result/`, `tiger/`
- 생성 산출물과 캐시: `final/output/`, `output/`, `__pycache__/`, `.pytest_cache/`

루트 스크립트 중 `5_extract_all_text_and_save_latex_split_images.py`에 있던 공용 구현은
`pipelines/legacy_split_images.py`로 내부화했습니다. 외부 실행 진입점으로는 사용하지 않습니다.
