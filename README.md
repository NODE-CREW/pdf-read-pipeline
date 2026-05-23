# PDF Reader

시험지 PDF에서 문항 텍스트와 문항 이미지를 추출하고, DB 적재 직전까지 사용할 수 있는 구조화 결과를 만드는 도구 모음입니다.

## 개요

- 대상:
  - 텍스트 레이어가 있는 PDF
  - 객관식/문항형 시험지 형식 PDF
- 범위:
  - 텍스트 추출
  - 문항 경계 추정
  - 문제/선택지 분리
  - 이미지 렌더링
  - OCR fallback
  - DB-ready JSONL 생성
- 범위 밖:
  - 실제 DB 연결/INSERT
  - 범용 문서 레이아웃 분석
  - 표/도형/이미지 자체의 구조적 해석

## 현재 상태

- 기본 텍스트 추출은 텍스트 기반 PDF에서 가장 안정적입니다.
- 스캔본/이미지 PDF는 `6-2`, `7-2`, `8`, `8-1`의 OCR fallback이 필요할 수 있습니다.
- 가장 실용적인 기본 실행 경로는 현재 `8_extract_all_text_and_save_latex_split_images.py`입니다.
- SaaS OCR을 붙일 수 있으면 `8-1_extract_all_text_and_save_latex_split_images.py`를 사용할 수 있습니다.
- `8-2_extract_all_text_and_save_latex_split_images.py`는 실험용입니다. 실제 시험지 데이터에서는 품질이 오히려 떨어지는 경우가 확인되었습니다.

## 추천 사용 흐름

1. 텍스트만 빠르게 확인하려면 `1` 또는 `2`
2. 문항 이미지와 텍스트를 함께 저장하려면 `5`
3. 여러 PDF를 안정적으로 처리하려면 `8`
4. SaaS OCR 우선 사용이 필요하면 `8-1`
5. `8-2`는 비교 실험이 필요한 경우에만 사용
6. 최종 JSON 스키마(`content`, `question_source`, `images`, `options`, 해설 포함)가 필요하면 `final/` 파이프라인을 사용

## 빠른 실행 예시

문항 텍스트를 콘솔에서 확인:

```bash
python ./1_extract_text_and_print.py --pdf ./test.pdf --pages "1-3"
```

여러 PDF를 처리하고 문항 이미지/텍스트/JSONL까지 저장:

```bash
python ./8_extract_all_text_and_save_latex_split_images.py --pdf ./level2.pdf ./level3.pdf
```

opendataloader 기반 문제 구조 JSON을 바로 생성:

```bash
python3 ./11_run_exam_pdf_pipeline.py \
  ./tiger/sample/comh1_040215.pdf \
  --output-dir ./output/exam_pdf
```

`data/test-1.pdf`처럼 2단 레이아웃이 섞인 PDF를 `@output` 호환 JSON + 이미지 crop으로 추출:

```bash
python3 ./new/test1_parser.py \
  --pdf ./data/test-1.pdf \
  --output-dir ./new/output/test-1
```

최종 JSON 스키마로 변환:

```bash
python ./final/parse_pdf.py \
  --pdf ./data/test-1.pdf \
  --output-dir ./final/output/test-1 \
  --parser sinagong
```

상세 설계와 AI endpoint 설정은 [`final/README.md`](final/README.md)를 참고합니다.

SaaS OCR 우선 사용:

```bash
OCR_SAAS_ENDPOINT="https://your-ocr-saas.example/v1/ocr" \
OCR_SAAS_API_KEY="***" \
python ./8-1_extract_all_text_and_save_latex_split_images.py --pdf ./level2.pdf
```

## 출력 구조

멀티 PDF 계열 스크립트(`6` 이상)는 기본적으로 아래 구조를 만듭니다.

```text
output/
  <pdf파일명>/
    output.tex
    latex_pages/
      question_001_problem_part_01.png
      question_001_choices_part_01.png
      shared_passage_020_021_part_01.png
    question_texts/
      question_001_problem.txt
      question_001_choices.txt
      questions_db_ready.jsonl
```

- 같은 이름 폴더가 이미 있으면 `_<숫자>`가 붙어 충돌을 피합니다.
- DB-ready를 지원하지 않는 스크립트는 `questions_db_ready.jsonl`을 만들지 않습니다.

## 핵심 기능

- 텍스트 추출 엔진 우선순위:
  1. `PyMuPDF (fitz)`
  2. `pdfplumber`
  3. `pypdf`
- 문항 시작 패턴 인식:
  - `문 1`
  - `제 1 문`
  - `1.`
  - `1)`
- 선택지 패턴 유지:
  - `①~⑩`
  - `(1)~(5)`
  - `1.)~5.)`
  - 일부 OCR 대체 마커
- 컬럼 처리:
  - 텍스트 블록 간격 기반 2단 추론
  - 중앙 부근 세로 구분선 감지 시 separator 기반 컬럼 분리 보강
- 이미지 처리:
  - 문항 영역 렌더링
  - 문제/선택지 이미지 분리
  - 상/하단 경계선 refine
- OCR fallback:
  - 텍스트가 빈약한 문항 이미지에서 OCR 재시도
  - 필요 시 좌/우 분할 OCR 후보 평가
  - 다음 문항이 섞인 OCR 결과 자동 절단 시도
- DB-ready 출력:
  - 문항 텍스트
  - 문제/선택지 이미지 상대경로
  - 공통 지문 매핑
  - content hash

## 한계

- 텍스트 레이어가 없는 스캔본은 OCR 품질에 크게 의존합니다.
- 표, 차트, 삽화, 복잡한 수식 배치가 많은 문서는 정확도가 떨어질 수 있습니다.
- 보호/암호화 PDF, 레이아웃이 매우 특이한 PDF는 실패할 수 있습니다.
- 중앙 고정 2분할은 직관적이지만 실제 품질이 항상 좋아지지 않습니다.

## 스크립트 안내

### 기본 스크립트

1. `1_extract_text_and_print.py`
- 지정한 페이지 범위에서 텍스트를 추출하고 문항 단위로 콘솔 출력

2. `2_extract_all_text_and_print.py`
- PDF 전체 페이지의 텍스트를 페이지별로 콘솔 출력

3. `3_extract_all_text_and_save_latex.py`
- 페이지 또는 문항 영역을 PNG로 렌더링하고 LaTeX 파일 생성

4. `4_extract_all_text_and_save_latex.py`
- 3번 기능 + 문제/선택지 텍스트 분리 저장

5. `5_extract_all_text_and_save_latex_split_images.py`
- 4번 기능 + 문제/선택지 이미지까지 분리 저장

6. `6_extract_all_text_and_save_latex_split_images.py`
- 5번 기능 + 여러 PDF를 한 번에 처리
- 기본 입력은 GUI 파일 선택, `--pdf`로 직접 지정도 가능

7. `7_extract_all_text_and_save_latex_split_images.py`
- 6번 기능 + 생성된 이미지의 상/하단 경계선 refine

8. `8_extract_all_text_and_save_latex_split_images.py`
- 현재 기본 권장 버전
- image refine + OCR fallback + DB-ready + 컬럼 분리 보강

### 파생 스크립트

6-1. `6-1_extract_all_text_and_save_latex_split_images.py`
- `6` + DB-ready JSONL 생성

6-2. `6-2_extract_all_text_and_save_latex_split_images.py`
- `6-1` + OCR fallback

7-1. `7-1_extract_all_text_and_save_latex_split_images.py`
- `7` + DB-ready JSONL 생성

7-2. `7-2_extract_all_text_and_save_latex_split_images.py`
- `7-1` + OCR fallback

8-1. `8-1_extract_all_text_and_save_latex_split_images.py`
- `8` + SaaS OCR 우선 사용
- SaaS 실패 또는 미설정 시 로컬 OCR fallback

8-2. `8-2_extract_all_text_and_save_latex_split_images.py`
- `8` + 페이지 분석 시작 전에 중앙 2분할 우선 적용
- 실제 시험지에서는 기본 `8`/`8-1`보다 품질이 더 떨어지는 경우가 확인됨
- 실험용으로만 유지

## 스크립트 선택 가이드

- 텍스트 레이어 PDF를 빠르게 확인:
  - `1`, `2`
- 단일 PDF를 이미지+텍스트로 저장:
  - `5`
- 여러 PDF를 안정적으로 처리:
  - `8`
- SaaS OCR 연동:
  - `8-1`
- 중앙 2분할 실험:
  - `8-2`

## PDF to Markdown 변환

`pipelines/pdf_to_markdown.py`는 PDF를 Markdown으로 변환하는 새로운 파이프라인입니다.

### 주요 기능

- **opendataloader-pdf** 기반 PDF 파싱
- 텍스트 → Markdown 변환
- 그림/표/수식 → 이미지 추출 후 Markdown에 경로 삽입
- 문항별 분리 저장

### 실행 방법

```bash
python -m pipelines.pdf_to_markdown ./input.pdf -o ./output/
```

### 출력 구조

```text
output/<pdf파일명>/
├── document.md           # 전체 마크다운 문서
├── questions/            # 문항별 분리
│   ├── q001.md
│   ├── q002.md
│   └── ...
├── images/               # 추출된 이미지
│   ├── imageFile1.png
│   └── ...
├── raw_json/             # opendataloader 원본 출력
│   └── <pdf파일명>.json
└── metadata.json         # 변환 메타데이터
```

### Python에서 직접 사용

```python
from pathlib import Path
from pipelines.pdf_to_markdown import convert_pdf_to_markdown

result = convert_pdf_to_markdown(
    Path("./input.pdf"),
    Path("./output/"),
)

print(f"마크다운: {result.markdown_path}")
print(f"이미지: {result.image_count}개")
print(f"문항: {result.question_count}개")
```

### 의존성

```bash
pip install opendataloader-pdf
```

시스템 요구사항:
- **Java 11+** (opendataloader-pdf 필수)

## 시험지형 PDF 질문 JSON 추출

`11_run_exam_pdf_pipeline.py`는 `result/pdf_split_answer_concept_extract/1-1_extract_questions_from_json.py`와 같은 계열로 동작합니다.

- 먼저 `opendataloader-pdf`로 임시 JSON을 생성하고
- 그 다음 `pipelines.question_parser.parse_pdf_json()`으로 문제 구조 JSON을 만듭니다.

즉 출력 스키마는 `question_parser` 기준이며, 텍스트/선택지/이미지/crop이 분리된 **md-ready 구조**를 만듭니다.

### 출력 구조 특징

- top-level: `source`, `questions`, `image_crops`, `metadata`
- question item: `question_number`, `page_number`, `question_text`, `description`, `choices`, `images`, `bounding_box`
- 이미지 crop은 top-level `image_crops`에 모이고, 각 `images[]` / `choice.image`에 `crop_path`가 연결됩니다.

### 실행 방법

```bash
python3 ./11_run_exam_pdf_pipeline.py \
  ./tiger/sample/comh1_040215.pdf \
  --output-dir ./output/exam_pdf
```

여러 PDF를 한 번에 처리할 수도 있습니다.

```bash
python3 ./11_run_exam_pdf_pipeline.py \
  ./20190302.pdf ./20190831.pdf \
  --output-dir ./output/exam_pdf
```

### 출력 파일

```text
output/exam_pdf/
  comh1_040215_questions.json
  crops/
    crop_id0001_p1.png
```

`new/test1_parser.py`는 아래 구조를 만듭니다.

```text
new/output/test-1/
  test-1_questions.json
  crops/
    crop_id0001_p2.png
    crop_id0002_p2.png
```

- top-level 키: `source`, `questions`, `image_crops`, `metadata`
- question item 키: `question_number`, `page_number`, `question_text`, `description`, `choices`, `images`, `bounding_box`
- `images[]`와 top-level `image_crops[]`의 `crop_path`는 상대 경로 문자열입니다.
- `new/test1_parser.py`는 `data/test-1.pdf` 같은 2단 시험지 레이아웃에서 header/footer를 제외하고 문제/선택지만 구조화합니다.

### Python에서 직접 사용

```python
from pathlib import Path
from pipelines.question_parser import parse_pdf_json

result = parse_pdf_json(
    Path("./raw_json/comh1_040215.json"),
    pdf_path=Path("./tiger/sample/comh1_040215.pdf"),
    out_dir=Path("./output/exam_pdf"),
)
print(result["metadata"])
```

## 텍스트 기반 문제 추출 (JSON → 구조화 JSON)

`pipelines/question_parser.py`는 opendataloader-pdf가 생성한 JSON에서 헤더/푸터를 제거하고, 문제·선택지를 파싱하여 구조화 JSON을 출력합니다. OCR 없이 텍스트 구조를 유지합니다.

### 노이즈 제거 방식

- **헤더/푸터/캡션**: JSON의 `type == "header"`, `"footer"`, `"caption"` 노드를 명시적으로 필터링합니다.
- **2단 컬럼 구분선**: 별도 처리가 필요하지 않습니다. opendataloader-pdf는 PDF 구조를 직접 파싱하여 읽기 순서대로 텍스트를 추출하므로, 2단 레이아웃의 왼쪽 컬럼 → 오른쪽 컬럼 순서로 `list` 노드가 이미 분리되어 나옵니다. 중앙 구분선은 JSON에 별도 노드로 나타나지 않으므로 제거할 대상 자체가 없습니다.

> 기존 `base.py`의 `infer_vertical_separator_x()`, `detect_vertical_separator_x_in_page()` 등은 이미지 기반으로 픽셀을 분석해서 세로선을 감지했지만, opendataloader JSON 방식에서는 이 과정이 불필요합니다.

### 실행 방법

**권장**: PDF 파일만 지정 (자동으로 JSON 생성 후 파싱)

```bash
python result/pdf_split_answer_concept_extract/1-1_extract_questions_from_json.py \
  --pdf tiger/sample/comh1_040215.pdf \
  --out-dir output/comh1_040215_questions
```

**고급**: JSON이 이미 있는 경우 직접 지정

```bash
python result/pdf_split_answer_concept_extract/1-1_extract_questions_from_json.py \
  --json tiger/sample/comh1_040215.json \
  --pdf tiger/sample/comh1_040215.pdf \
  --out-dir output/comh1_040215_questions
```

#### 파라미터 설명

- `--pdf`: 원본 PDF 파일 경로
  - `--json` 없이 단독 사용 가능 (자동으로 임시 JSON 생성 후 삭제)
  - `--json`과 함께 사용 시 이미지 crop도 수행
- `--json`: opendataloader-pdf JSON 파일 경로 (선택)
  - 생략 시 `--pdf`로부터 자동 생성 (권장)
  - 직접 지정 시 JSON 생성 단계 건너뜀
- `--out-dir`: 출력 디렉토리 (필수)
- `--dpi`: 이미지 crop 해상도 (기본 150)
  - **150 DPI**: 화면 표시/일반 OCR (기본값, 권장)
  - **200-300 DPI**: 고품질 OCR/인쇄
  - **400-600 DPI**: 정밀 분석 (파일 크기 증가, 메모리 주의)
  - 600 DPI 초과는 메모리 이슈로 비권장

> **내부 동작**: `--json` 없이 `--pdf`만 사용하면, 스크립트가 자동으로 opendataloader-pdf를 호출하여 임시 디렉토리에 JSON을 생성하고, 파싱 완료 후 임시 JSON을 삭제합니다.

### 출력 구조

```text
output/<pdf파일명>_questions/
├── <pdf파일명>_questions.json   # 문제별 구조화 JSON
└── crops/                       # bbox 기반 이미지 crop
    ├── crop_id0016_p1.png
    └── ...
```

### Python에서 직접 사용

```python
from pathlib import Path
from pipelines.question_parser import parse_pdf_json

result = parse_pdf_json(
    Path("tiger/sample/comh1_040215.json"),
    pdf_path=Path("tiger/sample/comh1_040215.pdf"),
    out_dir=Path("output/comh1_040215_questions"),
)

print(f"문제 수: {result['metadata']['total_questions']}")
print(f"첫 문제: {result['questions'][0]['question_text']}")
```

## 공통 파이프라인 모듈

`6-1`, `6-2`, `7-1`, `7-2`, `8`, `8-1`, `8-2`는 `pipelines/` 패키지의 공통 구현을 공유합니다.

- `pipelines/base.py`
  - 공통 추출/렌더/문서화 오케스트레이션
- `pipelines/refine.py`
  - 이미지 경계선 refine
- `pipelines/db_ready.py`
  - DB-ready JSONL 생성
- `pipelines/ocr.py`
  - OCR fallback
- `pipelines/split_images_pipeline.py`
  - 공통 파이프라인 재노출용 façade
- `pipelines/pdf_to_markdown.py`
  - PDF → Markdown 변환
- `pipelines/question_parser.py`
  - opendataloader JSON → 문제별 구조화 JSON 추출

## OCR 실행 환경

`6-2`, `7-2`, `8`, `8-1`, `8-2`에서 OCR 기능을 제대로 쓰려면 아래가 필요합니다.

- Python 패키지:
  - `pytesseract`
  - `Pillow`
- 시스템 바이너리:
  - `tesseract`
- 언어 데이터:
  - `kor`
  - `eng`

macOS(Homebrew) 예시:

```bash
brew install tesseract tesseract-lang
python3 -m pip install pytesseract pillow
```

확인:

```bash
which tesseract
tesseract --list-langs | rg "kor|eng"
```

## SaaS OCR 환경

`8-1`은 아래 환경 변수를 사용합니다.

- `OCR_SAAS_ENDPOINT`
- `OCR_SAAS_API_KEY`
- `OCR_SAAS_TIMEOUT_SEC` 선택

SaaS OCR 호출이 실패하거나 환경 변수가 비어 있으면 자동으로 로컬 OCR fallback을 시도합니다.

## 실행 예시 모음

단일 PDF 전체 텍스트 확인:

```bash
python ./2_extract_all_text_and_print.py --pdf ./level2.pdf
```

문항 이미지와 텍스트 저장:

```bash
python ./5_extract_all_text_and_save_latex_split_images.py --pdf ./level5.pdf
```

여러 PDF 처리:

```bash
python ./6_extract_all_text_and_save_latex_split_images.py --pdf ./level2.pdf ./level3.pdf
```

OCR fallback 포함:

```bash
python ./7-2_extract_all_text_and_save_latex_split_images.py --pdf ./level2.pdf
```

현재 기본 권장 경로:

```bash
python ./8_extract_all_text_and_save_latex_split_images.py --pdf ./level2.pdf
```

디렉토리 안의 `.txt` 파일들을 파일명 순서대로 하나로 합치려면 아래 스크립트를 사용합니다.

```bash
python3 ./concat_text_files.py \
  ./output/20200229_8/exam_concepts_txt \
  --output ./output/20200229_8/all_concepts.txt
```

이 스크립트는 아래 규칙으로 동작합니다.

- 입력 디렉토리 바로 아래의 `.txt` 파일만 대상으로 함
- 파일명 오름차순으로 이어붙임
- 출력 파일이 입력 디렉토리 안에 있어도 자기 자신은 다시 읽지 않음
- 앞 파일 끝에 줄바꿈이 없을 때만 다음 파일 앞에 줄바꿈 1개를 추가
- 결과는 UTF-8로 저장

시험 문제 이미지 2~3장을 GPT-5 mini로 분석해 정답/해설 JSON을 txt로 저장:

```bash
python3 ./9_generate_exam_answer_json_to_txt.py \
  --image ./output/level5/latex_pages/question_002_problem_part_01.png \
  --image ./output/level5/latex_pages/question_002_choices_part_01.png \
  --output ./output/level5/answer-2.txt
```

`test_id`, `question_id`를 직접 지정하려면 아래처럼 선택 인자를 추가하면 됩니다.

```bash
python3 ./9_generate_exam_answer_json_to_txt.py \
  --image ./question.png \
  --image ./choices_1.png \
  --test-id 1 \
  --question-id 101 \
  --output ./answer.txt
```

이 스크립트는 아래를 함께 적용합니다.

- `gpt-5-mini` 기본 사용
- 이미지 입력 `detail: "high"` 고정
- 첫 번째 `--image`를 문제 이미지, 나머지 `--image`를 선택지 이미지로 사용
- 프롬프트용 입력 JSON은 내부에서 자동 생성
- `--test-id`, `--question-id`를 생략하면 둘 다 `1` 사용
- JSON Schema 기반 구조화 출력 강제
- 스마트 따옴표/JSON 파싱 실패 시 자동 재시도
- 최종 결과를 2칸 들여쓰기 pretty JSON으로 `.txt` 저장

`latex_pages` 디렉토리 안의 `question_001_*`, `question_002_*` 같은 파일들을 문제 번호별로 묶어서 [`9_generate_exam_answer_json_to_txt.py`](./9_generate_exam_answer_json_to_txt.py)를 순차 호출하려면 아래 배치 스크립트를 사용합니다.

```bash
python3 ./10_batch_generate_exam_answer_json_to_txt.py \
  ./output/20200229_8/latex_pages
```

기본 출력 경로는 입력 디렉토리 상위의 `exam_answer_txt/`이며, 예를 들면 아래처럼 저장됩니다.

- `./output/20200229_8/exam_answer_txt/question_001_answer.txt`
- `./output/20200229_8/exam_answer_txt/question_002_answer.txt`
- `...`
- `./output/20200229_8/exam_answer_txt/question_060_answer.txt`

`--test-id`, `--output-dir`, `--start-question-number`도 함께 사용할 수 있습니다.

```bash
python3 ./10_batch_generate_exam_answer_json_to_txt.py \
  ./output/20200229_8/latex_pages \
  --test-id 20200229 \
  --start-question-number 26
```

시험 문제 이미지 2~3장을 GPT-5 mini로 분석해 공통 학습 개념 JSON을 txt로 저장:

```bash
python3 ./9-1_generate_exam_concepts_json_to_txt.py \
  --image ./question_7.png \
  --image ./question_8.png \
  --question-id 7 \
  --question-id 8 \
  --output ./concept_result.txt
```

`--question-id`를 생략하면 이미지 순서대로 `1, 2, 3`이 자동 부여됩니다.

```bash
python3 ./9-1_generate_exam_concepts_json_to_txt.py \
  --image ./problem-4.png \
  --image ./problem-25.png \
  --output ./output/level5/concept_result.txt
```

이 스크립트도 아래를 함께 적용합니다.

- `gpt-5-mini` 기본 사용
- 이미지 입력 `detail: "high"` 고정
- JSON Schema 기반 구조화 출력 강제
- 스마트 따옴표 포함 여부 검사와 JSON 파싱 실패 시 자동 재시도
- 최종 결과를 2칸 들여쓰기 pretty JSON으로 `.txt` 저장

`latex_pages` 디렉토리 안의 `question_001_*`, `question_002_*` 같은 파일들을 문제 번호별로 묶어서 [`9-1_generate_exam_concepts_json_to_txt.py`](./9-1_generate_exam_concepts_json_to_txt.py)를 순차 호출하려면 아래 배치 스크립트를 사용합니다.

```bash
python3 ./10-1_batch_generate_exam_concepts_json_to_txt.py \
  ./output/20200229_8/latex_pages
```

기본 출력 경로는 입력 디렉토리 상위의 `exam_concepts_txt/`이며, 예를 들면 아래처럼 저장됩니다.

- `./output/20200229_8/exam_concepts_txt/question_001_concepts.txt`
- `./output/20200229_8/exam_concepts_txt/question_002_concepts.txt`
- `...`
- `./output/20200229_8/exam_concepts_txt/question_060_concepts.txt`

출력 디렉토리를 직접 지정하려면 `--output-dir`를 추가하면 됩니다.

```bash
python3 ./10-1_batch_generate_exam_concepts_json_to_txt.py \
  ./output/20200229_8/latex_pages \
  --output-dir ./output/20200229_8/custom_concepts_txt
```

특정 문제번호부터 다시 시작하려면 `--start-question-number`를 사용합니다.

```bash
python3 ./10-1_batch_generate_exam_concepts_json_to_txt.py \
  ./output/20200229_8/latex_pages \
  --start-question-number 26
```

이 스크립트는 아래를 함께 적용합니다.

- `question_XXX_*` 파일만 수집
- 문제 번호 기준 오름차순 실행
- `--start-question-number`를 주면 해당 문제번호부터만 실행
- 같은 문제의 `problem/choices/part` 이미지를 한 묶음으로 전달
- 묶인 이미지 수만큼 같은 `--question-id`를 반복 전달
- 개별 문제 실행 실패 시 해당 문제 번호와 함께 즉시 중단

모든 입력 이미지에 대해 공통 학습 개념을 반드시 1개만 생성하도록 강제하려면 아래 스크립트를 사용합니다.

```bash
python3 ./9-2_generate_exam_single_concept_json_to_txt.py \
  --image ./problem-4.png \
  --image ./problem-25.png \
  --output ./output/level5/concept_result2.txt
```

이 스크립트는 아래를 추가로 강제합니다.

- `concepts` 배열 길이 1 고정
- 입력된 모든 `question_id`가 하나의 동일한 `concept_id`에 정확히 한 번씩만 매핑
- 모델이 여러 concept를 반환하면 검증 실패로 재시도

`latex_pages` 디렉토리 안의 `question_001_*`, `question_002_*` 같은 파일들을 문제 번호별로 묶어서 [`9-2_generate_exam_single_concept_json_to_txt.py`](./9-2_generate_exam_single_concept_json_to_txt.py)를 순차 호출하려면 아래 배치 스크립트를 사용합니다.

```bash
python3 ./10-2_batch_generate_exam_single_concept_json_to_txt.py \
  ./output/20200229_8/latex_pages
```

기본 출력 경로는 입력 디렉토리 상위의 `exam_single_concept_txt/`이며, 예를 들면 아래처럼 저장됩니다.

- `./output/20200229_8/exam_single_concept_txt/question_001_single_concept.txt`
- `./output/20200229_8/exam_single_concept_txt/question_002_single_concept.txt`
- `...`
- `./output/20200229_8/exam_single_concept_txt/question_060_single_concept.txt`

출력 디렉토리를 직접 지정하거나 특정 문제번호부터 다시 시작하려면 아래처럼 실행합니다.

```bash
python3 ./10-2_batch_generate_exam_single_concept_json_to_txt.py \
  ./output/20200229_8/latex_pages \
  --output-dir ./output/20200229_8/custom_single_concept_txt \
  --start-question-number 26
```

실행 전 준비:

```bash
python3 -m pip install openai
```
