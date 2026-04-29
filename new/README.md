# `data/test-1.pdf` 전용 파서 설명서

이 문서는 `new/test1_parser.py`가 **어떤 방식으로 `data/test-1.pdf`를 파싱하는지**, 그리고 **실제로 어떻게 실행하는지**를 설명합니다.

이 PDF는 겉보기에는 파싱이 잘 안 되는 시험지 PDF처럼 보이지만, 완전히 이미지 스캔본은 아닙니다. 핵심은 **텍스트 레이어는 살아 있는데, 평범한 텍스트 추출로는 2단 레이아웃이 섞여서 문항 순서가 깨진다**는 점입니다.

즉, 이 스크립트는 OCR-first 방식이 아니라 **PyMuPDF(`fitz`) 기반 좌표(bbox) 파싱 방식**으로 동작합니다.

---

## 왜 일반적인 추출이 잘 안 되는가

`test-1.pdf`는 다음 특징 때문에 단순한 `page.get_text()`나 `pdftotext`류 결과가 깨집니다.

1. **2단 컬럼 시험지 레이아웃**
   - 왼쪽 컬럼 문제를 다 읽기 전에 오른쪽 컬럼 문제 텍스트가 섞입니다.
   - 예: `14번` 다음에 같은 페이지 오른쪽 컬럼의 `23번`이 붙어 나오는 식입니다.

2. **헤더/푸터/저작권 문구가 반복적으로 섞임**
   - `1 회`
   - `2024 년 1 회 정보처리기사 필기`
   - `기출문제 & 정답 및 해설`
   - 저작권 안내 문구
   - `- 1 -`, `- 2 -` 같은 페이지 번호

3. **마지막 페이지는 문제 페이지가 아니라 정답표 페이지**
   - 8페이지는 `정답 및 해설` 페이지라 문제 본문과 분리해서 다뤄야 합니다.

그래서 이 파일은 “텍스트가 없어서 파싱이 안 되는 PDF”가 아니라, **텍스트는 있으나 읽기 순서와 노이즈 제거를 제대로 처리하지 않으면 실패하는 PDF**입니다.

---

## 현재 스크립트가 사용하는 정확한 방법

`new/test1_parser.py`는 아래 순서로 동작합니다.

### 1) PDF를 OCR이 아니라 `fitz`로 연다

스크립트는 `PyMuPDF`의 `fitz`를 사용합니다.

- 사용 함수: `fitz.open(pdf_path)`
- 이유: 텍스트, 단어 좌표, 페이지 렌더링, crop 저장을 한 번에 처리할 수 있기 때문입니다.

이 구현은 `page.get_text("words")`를 사용해서 **단어별 좌표**를 읽습니다.

---

### 2) 페이지별 본문 영역을 하드코딩으로 제한한다

`test-1.pdf` 전용 구현이라 페이지별 상/하단 경계를 고정값으로 사용합니다. 다만 본문 처리 페이지 수는 전체 페이지 수를 그대로 고정하지 않고, **마지막 페이지를 정답표로 간주해 제외**하는 방식으로 처리합니다.

```python
def page_content_bounds(page_number: int) -> tuple[float, float]:
    if page_number == 1:
        return 215.0, 790.0
    return 60.0, 790.0
```

의미는 다음과 같습니다.

- **1페이지**: 상단 배너와 저작권 박스가 커서 `y < 215`는 버립니다.
- **2페이지 이후 마지막 전 페이지까지**: 일반 페이지이므로 `y < 60`, `y > 790`를 버립니다.
- **마지막 페이지**: 문제 본문이 아니라 정답표 페이지로 간주하고, 본문 추출 루프에서 제외합니다.

---

### 3) 한 페이지를 왼쪽/오른쪽 컬럼으로 강제 분리한다

이 PDF가 안 읽히는 가장 큰 이유가 여기입니다.

스크립트는 페이지의 가운데 x축을 기준으로 단어를 두 그룹으로 나눕니다.

```python
mid_x = page.rect.width / 2
target = left_words if ((x0 + x1) / 2) < mid_x else right_words
```

즉,

- 가운데보다 왼쪽 중심에 있는 단어 → **왼쪽 컬럼**
- 가운데보다 오른쪽 중심에 있는 단어 → **오른쪽 컬럼**

으로 강제 분리합니다.

그 다음 읽기 순서를 이렇게 고정합니다.

1. 왼쪽 컬럼 위→아래
2. 오른쪽 컬럼 위→아래

이 과정을 하지 않으면 문항 순서가 섞여서 문제 분리가 거의 안 됩니다.

---

### 4) 단어들을 다시 한 줄(line)로 묶는다

`page.get_text("words")`는 단어 단위 결과이므로 그대로는 문제를 읽기 어렵습니다.

스크립트는 y 좌표가 거의 같은 단어들끼리 한 줄로 묶습니다.

```python
if abs(y0 - last_y) <= 3.0:
    last_group.append(word)
```

그리고 x 좌표 순으로 정렬해 다시 문장처럼 합칩니다.

---

### 5) 헤더/푸터/노이즈 라인을 텍스트 패턴으로 제거한다

`should_skip_line()`에서 아래 문자열들을 버립니다.

- `1 회`
- `정답 및 해설`
- `저작권 안내`
- `2024 년 1 회 정보처리기사 필기`
- `기출문제 & 정답 및 해설`
- `이 자료는 시나공 카페 회원...`
- `다른 매체에 옮겨 실을 수 없으며...`
- `※ 다음 문제를 읽고 알맞은 것을 골라...`
- `답란 (...)`
- `제 1 과목`, `제 2 과목` 같은 과목 헤더
- `- 1 -`, `- 2 -` 같은 푸터

즉, 이 스크립트는 일반적인 의미 기반 필터가 아니라 **`test-1.pdf`에서 실제 보이는 노이즈 문자열을 직접 제거하는 방식**입니다.

---

### 6) 문항 시작은 `숫자 + 점` 패턴으로 찾는다

문항 시작은 아래 정규식으로 찾습니다.

```python
QUESTION_RE = re.compile(r"^(\d{1,3})\.\s*(.*)$")
```

예:

- `1. ...`
- `14. ...`
- `100. ...`

새 문제 번호가 나오기 전까지의 라인들을 모두 현재 문제에 누적합니다.

---

### 7) 선택지는 `①②③④` 패턴으로 분리한다

선택지 분리는 다음 정규식으로 처리합니다.

```python
CHOICE_RE = re.compile(r"([①②③④])")
```

즉,

- 첫 `①` 이전 텍스트 → `question_text`
- 각 선택지 마커 사이 텍스트 → `choices[].text`

로 나눕니다.

예를 들어 아래 텍스트가 있으면:

```text
... 구성되는 것은? ① Coad 와 Yourdon 방법 ② Booch 방법 ③ Jacobson 방법 ④ Wirfs-Brocks 방법
```

결과는:

- `question_text`: `... 구성되는 것은?`
- `choices[0].text`: `Coad 와 Yourdon 방법`
- `choices[1].text`: `Booch 방법`
- `choices[2].text`: `Jacobson 방법`
- `choices[3].text`: `Wirfs-Brocks 방법`

---

### 8) 결과를 `@output` 계열 JSON 구조로 저장한다

스크립트는 최종적으로 아래 top-level 구조를 만듭니다.

```json
{
  "source": "test-1.pdf",
  "questions": [...],
  "image_crops": [...],
  "metadata": {...}
}
```

문항 하나는 대략 이런 구조입니다.

```json
{
  "question_number": 1,
  "page_number": 1,
  "question_text": "객체지향 분석 방법론 중 ...",
  "description": "",
  "choices": [
    {"number": 1, "text": "..."},
    {"number": 2, "text": "..."},
    {"number": 3, "text": "..."},
    {"number": 4, "text": "..."}
  ],
  "images": [],
  "bounding_box": [x0, y0, x1, y1]
}
```

---

## 이미지 crop은 현재 어떻게 처리하는가

현재 구현은 **3단계**로 처리합니다.

1. `page.cluster_drawings()`로 표/도식/배치 블록 후보를 먼저 수집
2. **박스 안 설명문/코드/숫자리스트**는 먼저 crop으로 분리하고, 그 라인은 `question_text`에서 제거
3. 텍스트로 충분히 표현 가능한 후보는 버리고, 놓친 트리 도형은 bbox 렌더 후 텍스트 마스킹 방식으로 fallback 복구

```python
for rect_like in page.cluster_drawings():
    rect = fitz.Rect(rect_like)
```

이후 각 후보에 대해 아래 순서로 적용합니다.

- **boxed text crop 분리**: 박스 안에 있는 설명문/코드/숫자리스트 라인을 찾아 crop 저장
- **question_text 재구성**: crop으로 보낸 라인을 제외하고 본문/선택지를 다시 조립
- **텍스트-heavy 후보 제거**: 비텍스트 crop 단계에서는 후보 rect 안의 텍스트 점유율이 높으면 버림
- **텍스트로 표현 가능한 코드/SQL/숫자리스트 제거**: 이미 boxed text crop으로 처리된 경우 중복 crop 방지
- **트리 도형 fallback**: `cluster_drawings()`가 놓친 트리 문제는 문항 bbox를 렌더한 뒤 단어 영역을 흰색으로 지우고, 남은 비텍스트 픽셀이 충분할 때만 crop 저장

즉, 지금은 **“박스 안 텍스트를 image로 옮기고 question_text에서는 제거”**하는 흐름이 들어 있습니다.

### 중요한 한계

현재 기준으로는 **차단 이슈였던 텍스트-only crop 문제는 제거된 상태**입니다.

최종 검수에서 확인된 결과:

- 설명문만 있는 crop(`Q14`, `Q24`, `Q97`)은 더 이상 저장되지 않습니다.
- 실제 트리 도형(`Q23`, `Q28`)은 crop으로 복구됩니다.
- 표 구조가 중요한 문항(`Q51`, `Q66`, `Q89`)은 crop으로 유지됩니다.
- 박스 안 설명문/코드/숫자리스트(`Q14`, `Q24`, `Q26`, `Q67`, `Q69`, `Q97`)는 crop으로 저장되고, 그 내용은 `question_text`에서 제거됩니다.

즉 현재 스크립트는:

- 문제/선택지 **텍스트 추출**
- **박스 안 설명문/코드/숫자리스트 → image crop 분리**
- 실제 **트리/표 같은 시각 정보 crop**
- **crop 대상 블록의 question_text 제거**

까지는 통과한 상태입니다.

다만 완전한 범용 이미지 분리는 아니라서, 다른 시험지 PDF에 그대로 일반화되지는 않습니다.

---

## 왜 이 방법은 그동안 안 되던 케이스를 어느 정도 풀 수 있었는가

핵심은 세 가지입니다.

1. **OCR로 접근하지 않았다**
   - 이 PDF는 이미지 스캔본이 아니라 텍스트 레이어가 살아 있습니다.
   - OCR보다 좌표 기반 텍스트 추출이 더 정확합니다.

2. **2단 컬럼을 강제로 분리했다**
   - 일반 텍스트 추출이 실패하는 가장 큰 원인이 컬럼 혼합인데, 이걸 직접 끊었습니다.

3. **페이지별 노이즈를 하드코딩으로 제거했다**
   - 범용성은 낮지만 `test-1.pdf` 하나만 보면 안정성이 올라갑니다.

즉, 이 스크립트는 “범용 PDF 파서”가 아니라 **`test-1.pdf`를 읽기 위해 레이아웃 가정을 직접 반영한 전용 파서**입니다.

---

## 의존성 설치

최소 필요 패키지는 아래입니다.

```bash
python3 -m pip install PyMuPDF Pillow
```

프로젝트 `requirements.txt` 기준으로 설치하려면:

```bash
python3 -m pip install -r requirements.txt
```

---

## 실행 방법

### 기본 실행

프로젝트 루트에서 아래처럼 실행합니다.

```bash
python3 ./new/test1_parser.py \
  --pdf ./data/test-1.pdf \
  --output-dir ./new/output/test-1
```

실행이 끝나면 JSON 파일 경로를 한 줄 출력합니다.

예:

```text
new/output/test-1/test-1_questions.json
```

---

### DPI를 바꿔 crop 저장

```bash
python3 ./new/test1_parser.py \
  --pdf ./data/test-1.pdf \
  --output-dir ./new/output/test-1-dpi200 \
  --dpi 200
```

`--dpi`는 crop PNG 렌더 해상도만 바꾸고, 텍스트 파싱 로직은 바꾸지 않습니다.

---

## 출력 구조

```text
new/output/test-1/
  test-1_questions.json
  crops/
    crop_id0001_p2.png
    crop_id0002_p2.png
    ...
```

### `test-1_questions.json`

- `source`: 원본 PDF 파일명
- `questions`: 문항 배열
- `image_crops`: 생성된 crop 메타데이터 배열
- `metadata.total_questions`: 추출된 총 문항 수
- `metadata.pages`: 원본 PDF 전체 페이지 수
- `metadata.generated_image_crops`: 저장된 crop 개수

---

## Python에서 직접 사용

```python
from pathlib import Path
from new.test1_parser import parse_test1_pdf

result = parse_test1_pdf(
    Path("./data/test-1.pdf"),
    out_dir=Path("./new/output/test-1"),
    dpi=150,
)

print(result["metadata"])
print(result["questions"][0])
```

---

## 이 스크립트가 전제로 하는 가정

이 구현은 아래 가정을 전제로 합니다.

1. **마지막 페이지는 정답표**다.
2. **마지막 페이지를 제외한 앞쪽 페이지들은 문제 본문**이다.
3. 문제는 `1.`, `2.`, `3.` 같은 형식으로 시작한다.
4. 선택지는 `①②③④` 형식이다.
5. 2단 컬럼은 페이지 중앙 기준으로 나눠도 된다.
6. 1페이지 헤더/저작권 박스 높이는 현재 파일과 유사하다.

이 중 하나라도 크게 바뀌면 결과가 깨질 수 있습니다.

---

## 현재 한계

### 1. 범용 PDF용이 아니다

이 코드는 `test-1.pdf` 전용 가정이 많습니다.

- 본문 y 범위 고정
- 헤더/푸터 문자열 고정
- 마지막 페이지 정답표 가정

### 2. 이미지 crop은 `test-1.pdf` 기준으로 튜닝되어 있다

현재 crop 로직은 `test-1.pdf` 기준으로 다음을 맞추도록 튜닝되어 있습니다.

- 설명 텍스트 crop 제거
- 박스 설명문/코드/숫자리스트 분리
- 트리 도형 복구
- 표 구조 유지

따라서 이 로직은 **현재 파일 기준으로는 검수 통과 상태**지만, 다른 레이아웃 PDF에서는 다시 조정이 필요할 수 있습니다.

### 3. 정답표는 아직 JSON에 넣지 않는다

마지막 페이지 정답표는 현재 문제 추출에서 제외할 뿐이고, 별도의 `answer` 필드로 매핑하지는 않습니다.

---

## 디버깅 팁

### 문항 수가 100이 아니면

- 컬럼 분리 또는 헤더 제거가 깨졌을 가능성이 큽니다.
- `page_content_bounds()`와 `should_skip_line()`를 먼저 확인하세요.

### 문제 텍스트에 헤더 문구가 섞이면

- `should_skip_line()`에 실제 섞인 문자열을 추가해야 합니다.

### crop이 이상하면

- `cluster_drawings()` 후보가 과도하게 잡히는지 먼저 확인하세요.
- 박스 안 텍스트가 `question_text`에 남아 있으면 `attach_boxed_text_crops()`의 라인 매칭 조건을 확인하세요.
- 트리 문제인데 crop이 비어 있으면 `detect_non_text_visual_rect()` fallback 조건을 확인하세요.
- 코드/SQL이 이미지로 저장되면 `is_text_representable_visual()` 필터 조건을 조정하세요.

---

## 요약

`test-1.pdf`를 읽는 핵심 방법은 아래 한 줄로 정리됩니다.

> **OCR이 아니라 `fitz`의 텍스트 좌표를 읽고, 2단 컬럼을 강제로 복원한 뒤, 박스 안 설명문은 먼저 image crop으로 분리하고, 마지막에 표/트리 같은 시각 정보까지 crop 하는 방식**

그래서 일반 추출기로는 깨지던 문항 순서를 복원할 수 있었고, `@output` 계열 JSON과 함께 **박스 설명문/코드/숫자리스트/표/트리**를 image crop으로 분리할 수 있습니다. 현재 구현은 범용 파서가 아니라, **`test-1.pdf` 검수 통과를 목표로 튜닝된 전용 파서**로 이해하는 것이 가장 정확합니다.
