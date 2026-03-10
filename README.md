# PDF Reader (텍스트 추출/문항 분리)

현재 이 프로젝트는 **텍스트 레이어가 있는 PDF**를 대상으로, 지정한 페이지에서 텍스트를 추출하고 문항 단위로 분리해 출력합니다.

## 프로젝트 목표와 범위

- 최종 서비스 목표는 추출/분리 결과를 DB에 저장해 활용하는 것입니다.
- 다만 **이 저장소의 범위는 DB 저장 직전 단계(추출/정제/구조화 결과 생성)까지**입니다.
- 즉, 본 프로젝트에서는 DB 연결/INSERT를 직접 수행하지 않습니다.

## 현재 지원하는 PDF 유형

- 텍스트 기반 PDF (디지털 문서, 텍스트 선택/복사가 가능한 PDF)
- 객관식/문항형 텍스트가 포함된 시험지 형식 PDF

## 현재 구현 내용

- 입력 페이지 범위 파싱: `--pages "1,3-5,10"` 형식 지원
- 텍스트 추출 엔진 우선순위:
  1. `PyMuPDF (fitz)`
  2. `pdfplumber`
  3. `pypdf`
- 문항 분리(heuristic):
  - `문 1`, `제 1 문`, `1.`, `1)` 등의 시작 패턴 인식
  - 페이지 중앙 부근에 세로 구분선이 감지되면 좌/우 컬럼을 강제 분리해 문항 경계 계산
  - 선택지(①②③..., `(1)`, `(2)` ...) 라인 유지
  - 페이지를 넘는 문항 이어붙이기(기본 병합 로직)
- 출력:
  - 문항별 구분선
  - 추정 문항번호
  - 원본 페이지 번호

## 현재 한계 (중요)

- **현재는 텍스트 레이어 중심 PDF 처리만 안정적으로 지원합니다.**
- 스캔본(이미지 PDF), 사진 위주의 PDF는 텍스트 추출 결과가 비어 있을 수 있습니다.
- PDF 안에 이미지/도형(표, 차트, 다이어그램)이 있어도 현재는 해당 시각 요소 자체를 구조적으로 분석하지 않습니다.
- 보호/암호화 PDF, 레이아웃이 매우 복잡한 PDF는 분리 정확도가 떨어질 수 있습니다.

즉, 질문 주신 내용대로 **지금은 텍스트 위주 PDF만 가능한 상태**가 맞습니다.

## 실행 방법

```bash
python ./1_extract_text_and_print.py --pdf ./test.pdf --pages "1-3"
```

## 스크립트 설명 (1~8-1)

1. `1_extract_text_and_print.py`
- 역할: 지정한 페이지 범위에서 텍스트를 추출하고 문항 단위로 콘솔 출력
- 특징: 문항 시작 패턴 인식 + 지문/선택지 분리 출력
- 예시:
```bash
python ./1_extract_text_and_print.py --pdf ./level1.pdf --pages "1-3"
```

2. `2_extract_all_text_and_print.py`
- 역할: PDF 전체 페이지의 텍스트를 추출해 페이지별로 콘솔 출력
- 특징: 전체 문서 텍스트를 빠르게 점검할 때 사용
- 예시:
```bash
python ./2_extract_all_text_and_print.py --pdf ./level2.pdf
```

3. `3_extract_all_text_and_save_latex.py`
- 역할: PDF 페이지(또는 문항 영역)를 PNG로 렌더링하고, 이미지를 포함한 LaTeX 파일 생성
- 특징: 텍스트 추출보다 원본 수식/레이아웃 보존이 중요할 때 사용
- 예시:
```bash
python ./3_extract_all_text_and_save_latex.py --pdf ./level3.pdf
```

4. `4_extract_all_text_and_save_latex.py`
- 역할: 3번 기능 + 문항 텍스트를 문제/선택지로 분리하여 txt 파일 저장
- 출력:
  - LaTeX: `./output/output.tex`
  - 이미지: `./output/latex_pages/`
  - 텍스트: `./output/question_texts/question_XXX_problem.txt`, `question_XXX_choices.txt`
- 예시:
```bash
python ./4_extract_all_text_and_save_latex.py --pdf ./level4.pdf
```

5. `5_extract_all_text_and_save_latex_split_images.py`
- 역할: 4번 기능 + LaTeX용 PNG 이미지도 문제/선택지로 분리 저장
- 출력:
  - 문제 이미지: `question_XXX_problem_part_YY.png`
  - 선택지 이미지: `question_XXX_choices_part_YY.png`
  - 분리 텍스트: `question_XXX_problem.txt`, `question_XXX_choices.txt`
- 예시:
```bash
python ./5_extract_all_text_and_save_latex_split_images.py --pdf ./level5.pdf
```

6. `6_extract_all_text_and_save_latex_split_images.py`
- 역할: 5번 기능 + 여러 PDF를 한 번에 처리하여 PDF별 결과 폴더로 저장
- 입력:
  - 기본: GUI 파일 선택창에서 PDF 여러 개 선택
  - 옵션: `--pdf`로 여러 PDF 경로 직접 전달 가능
- 출력:
  - `./output/<pdf파일명>/output.tex`
  - `./output/<pdf파일명>/latex_pages/`
  - `./output/<pdf파일명>/question_texts/`
  - 같은 이름 폴더가 이미 있으면 `_<숫자>`를 붙여 충돌 방지
- 예시(GUI):
```bash
python ./6_extract_all_text_and_save_latex_split_images.py
```
- 예시(CLI):
```bash
python ./6_extract_all_text_and_save_latex_split_images.py --pdf ./level2.pdf ./level3.pdf
```


6-1. `6-1_extract_all_text_and_save_latex_split_images.py`
- 역할: 6번 기능 + DB 적재 직전 표준 JSONL(`questions_db_ready.jsonl`) 생성
- 출력(기존 유지 + 추가):
  - `./output/<pdf파일명>/output.tex`
  - `./output/<pdf파일명>/latex_pages/`
  - `./output/<pdf파일명>/question_texts/`
  - `./output/<pdf파일명>/question_texts/questions_db_ready.jsonl`
- JSONL 스키마(문항 1건):
  - `schema_version`, `record_id`, `source_pdf_name`, `source_pdf_stem`
  - `question_index`, `question_number`, `question_text`, `choices_text`
  - `shared_passage_id`, `shared_passage_text`
  - `problem_image_paths`, `choices_image_paths`, `shared_passage_image_paths`
  - `content_hash`
- 예시(CLI):
```bash
python ./6-1_extract_all_text_and_save_latex_split_images.py --pdf ./level2.pdf ./level3.pdf
```


6-2. `6-2_extract_all_text_and_save_latex_split_images.py`
- 역할: 6-1 기능 + 스캔본 대비 OCR fallback(문항 텍스트 부재 시)
- OCR 동작:
  - 문항 텍스트(문제+선택지)가 비어 있으면 이미지(`problem/choices`)에서 OCR 재추출 시도
  - OCR 결과에서 `1.`, `2.` 같은 문항 시작 라인을 감지하면 단일 OCR 결과를 다문항으로 재구성
  - 세로 구분선이 감지되면 OCR도 좌/우 영역을 분리 인식한 뒤 결과를 병합
  - OCR 전처리(그레이스케일/이진화) 후 `psm 6` 우선, 실패 시 `psm 11`로 1회 재시도
  - 큰 폭 이미지(2단 의심)는 좌/우 분할 OCR 후보도 함께 평가해 최적 후보 선택
  - OCR 결과에 다음 문항이 섞이면 선택지 패턴(최소 3개) 이후의 다음 문항 시작 라인에서 자동 절단
  - OCR 선택지 마커는 `①~⑩`, `(1)~(5)`, `1.)~5.)`, `@` 패턴까지 허용
  - OCR 성공 시 기존 문항 분리 규칙으로 `question_text/choices_text` 재구성
  - `pytesseract` 또는 `Pillow` 미설치, `tesseract` 미설치 시 OCR 단계는 자동 건너뜀(경고 출력)
- 출력:
  - `./output/<pdf파일명>/output.tex`
  - `./output/<pdf파일명>/latex_pages/`
  - `./output/<pdf파일명>/question_texts/`
  - `./output/<pdf파일명>/question_texts/questions_db_ready.jsonl`
- 예시(CLI):
```bash
python ./6-2_extract_all_text_and_save_latex_split_images.py --pdf ./level2.pdf ./level3.pdf
```

7. `7_extract_all_text_and_save_latex_split_images.py`
- 역할: 6번 기능 + 생성된 문항/선택지/공통지문 이미지의 페이지 경계선(상·하단 잔선) refine
- refine 동작:
  - 이미지 상단/하단 edge row를 스캔해 경계선처럼 보이는 행을 감지하면 자동 crop
  - 이미지 본문 손실을 막기 위해 최대 trim 픽셀과 최소 높이 보호 조건 적용
  - Pillow 미설치 환경에서는 refine 단계를 건너뛰고 기존 6번 동작과 동일하게 처리
- 출력:
  - `./output/<pdf파일명>/output.tex`
  - `./output/<pdf파일명>/latex_pages/`
  - `./output/<pdf파일명>/question_texts/`
- 예시(GUI):
```bash
python ./7_extract_all_text_and_save_latex_split_images.py
```
- 예시(CLI):
```bash
python ./7_extract_all_text_and_save_latex_split_images.py --pdf ./level2.pdf ./level3.pdf
```

7-1. `7-1_extract_all_text_and_save_latex_split_images.py`
- 역할: 7번 기능 + DB 저장 직전 적재 포맷(JSONL) 생성
- 추가 출력:
  - `./output/<pdf파일명>/question_texts/questions_db_ready.jsonl`
- JSONL 레코드 포함 필드:
  - 문항 인덱스/번호, 문제/선택지 텍스트, 공통 지문 매핑, 이미지 상대경로, content hash
- 예시:
```bash
python ./7-1_extract_all_text_and_save_latex_split_images.py --pdf ./level2.pdf
```

7-2. `7-2_extract_all_text_and_save_latex_split_images.py`
- 역할: 7-1 기능 + OCR fallback으로 빈약한 텍스트 보강
- OCR 동작:
  - 추출 텍스트가 비어 있는 문항은 문항 이미지에 OCR 적용 후 문제/선택지 재분리
  - OCR 결과에서 `1.`, `2.` 같은 문항 시작 라인을 감지하면 단일 OCR 결과를 다문항으로 재구성
  - 세로 구분선이 감지되면 OCR도 좌/우 영역을 분리 인식한 뒤 결과를 병합
  - OCR 전처리(그레이스케일/이진화) 후 `psm 6` 우선, 실패 시 `psm 11`로 1회 재시도
  - 큰 폭 이미지(2단 의심)는 좌/우 분할 OCR 후보도 함께 평가해 최적 후보 선택
  - OCR 결과에 다음 문항이 섞이면 선택지 패턴(최소 3개) 이후의 다음 문항 시작 라인에서 자동 절단
  - OCR 선택지 마커는 `①~⑩`, `(1)~(5)`, `1.)~5.)`, `@` 패턴까지 허용
  - `pytesseract` + `Pillow` + `tesseract` 환경이 없으면 OCR 단계는 자동 건너뜀(경고 출력)
- 추가 출력:
  - `./output/<pdf파일명>/question_texts/questions_db_ready.jsonl`
- 예시:
```bash
python ./7-2_extract_all_text_and_save_latex_split_images.py --pdf ./level2.pdf
```

8. `8_extract_all_text_and_save_latex_split_images.py`
- 역할: 7-2의 후속 버전. OCR 적용 + 문제/선택지 분리 보강(세로 구분선 기준 컬럼 분리 포함)
- 동작:
  - image refine + DB-ready + OCR fallback
  - 세로 구분선 감지 시 좌/우 컬럼을 분리 인식하여 문항 분리
  - OCR 결과에서 문항 시작 패턴을 재탐지해 문제/선택지 텍스트를 재구성
- 예시:
```bash
python ./8_extract_all_text_and_save_latex_split_images.py --pdf ./level2.pdf
```

8-1. `8-1_extract_all_text_and_save_latex_split_images.py`
- 역할: 8번 기능 + SaaS OCR 우선 사용(실패/미설정 시 기존 Tesseract OCR fallback)
- 동작:
  - `OCR_SAAS_ENDPOINT`, `OCR_SAAS_API_KEY`가 설정되면 이미지 Base64를 SaaS OCR API로 전송
  - SaaS 응답에서 텍스트를 추출해 문항 분리 로직에 연결
  - SaaS 호출 실패(HTTP 오류/타임아웃/파싱 오류) 또는 미설정 시 기존 로컬 OCR(`pytesseract`) 자동 fallback
- 예시:
```bash
OCR_SAAS_ENDPOINT="https://your-ocr-saas.example/v1/ocr" \
OCR_SAAS_API_KEY="***" \
python ./8-1_extract_all_text_and_save_latex_split_images.py --pdf ./level2.pdf
```

## 파이프라인 공통 모듈

- `6-1`, `6-2`, `7-1`, `7-2`, `8`, `8-1`은 `pipelines/` 패키지의 공통 구현을 공유합니다.
- 모듈 구성:
  - `pipelines/base.py`: 공통 추출/렌더/문서화 오케스트레이션
  - `pipelines/refine.py`: 이미지 경계선 refine 관련 함수
  - `pipelines/db_ready.py`: DB-ready JSONL 생성 관련 함수
  - `pipelines/ocr.py`: OCR fallback 관련 함수
  - `pipelines/split_images_pipeline.py`: 하위 모듈을 재노출하는 호환 façade
- 각 스크립트는 기능 조합만 다릅니다.
  - `6-1`: DB-ready
  - `6-2`: DB-ready + OCR fallback
  - `7-1`: image refine + DB-ready
  - `7-2`: image refine + DB-ready + OCR fallback
  - `8`: image refine + DB-ready + OCR fallback (컬럼 분리/문항-선택지 분리 보강)
  - `8-1`: image refine + DB-ready + SaaS OCR 우선 + OCR fallback

## OCR 실행 환경 (6-2, 7-2, 8, 8-1 공통)

- 필수:
  - Python 패키지: `pytesseract`, `Pillow`
  - 시스템 바이너리: `tesseract`
  - 한글 OCR 데이터: `kor` (`kor+eng` 사용)
- macOS(Homebrew) 설치 예시:
```bash
brew install tesseract tesseract-lang
python3 -m pip install pytesseract pillow
```
- 설치 확인:
```bash
which tesseract
tesseract --list-langs | rg "kor|eng"
python3 -c "import pytesseract; from PIL import Image; print('ok')"
```

## SaaS OCR 환경 변수 (8-1)

- `OCR_SAAS_ENDPOINT`: SaaS OCR HTTP API endpoint (POST JSON)
- `OCR_SAAS_API_KEY`: SaaS API key (`Authorization: Bearer ...`로 전송)
- `OCR_SAAS_TIMEOUT_SEC`(선택): 요청 타임아웃(초), 기본 `30`

## 앞으로 추가할 항목

1. OCR 기반 추출
- 스캔본/이미지 PDF 페이지를 이미지로 변환 후 OCR 적용
- 텍스트 레이어 추출 실패 시 OCR 자동 fallback

2. 이미지/도형 포함 PDF 대응
- 페이지 내 텍스트/이미지/도형 영역 분리(레이아웃 분석)
- 표/차트/도형 주변 캡션 및 설명 텍스트 연계 추출
- 문항 단위로 "텍스트 + 시각 요소 메타정보" 함께 반환

3. 정확도 개선
- 과목/문서별 문항 시작 패턴 확장
- 헤더/푸터/쪽번호 노이즈 제거 규칙 강화
- 문항 분리 품질 검증용 테스트 케이스 추가
