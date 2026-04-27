# 시험지형 PDF 파싱 개선 설계안

## 1. 문제 정의

현재 `opendataloader` 기반 PDF 변환은 다음 유형에서 실패 가능성이 높다.

- 텍스트층은 존재하지만 레이아웃이 단순하지 않은 PDF
- 2단 시험지 레이아웃
- 페이지 상/하단 헤더, 푸터, 저작권 박스, 과목명, 페이지 번호가 섞인 PDF
- 문제 본문 중간에 이미지/도형이 포함된 PDF
- 문제 단위가 페이지/단(column) 경계를 넘는 PDF

**대상 PDF 특성:**
- 텍스트 추출 가능
- 본문 **2단 구조**
- 시각 요소(이미지/벡터/도형) 혼합
- 마지막 페이지에 **정답/해설 텍스트** 존재
- 단순 page-order 텍스트 추출로는 읽기 순서가 깨짐

> 본질은 OCR 부재가 아니라 **레이아웃 복원 및 문항 단위 세그멘테이션 실패**이다.

---

## 2. 목표

### 2.1 MVP 목표

다음 구조의 JSON 데이터를 안정적으로 생성한다.

```json
{
  "exam": {
    "title": "2024년 1회 정보처리기사 필기",
    "source_file": "...pdf"
  },
  "questions": [
    {
      "question_no": 1,
      "subject": "소프트웨어 설계",
      "page_range": [1, 1],
      "column_range": ["left", "left"],
      "stem": "객체지향 분석 방법론 중 ...",
      "choices": [
        {"label": "①", "text": "..."},
        {"label": "②", "text": "..."},
        {"label": "③", "text": "..."},
        {"label": "④", "text": "..."}
      ],
      "assets": [
        {
          "type": "image",
          "path": "assets/q001_img01.png",
          "bbox": [0, 0, 0, 0],
          "page": 1,
          "column": "left"
        }
      ],
      "answer": "①",
      "explanation": null,
      "raw_text": "...",
      "confidence": 0.93
    }
  ]
}
```

### 2.2 비목표

- 완전 스캔형 이미지 PDF 최고 수준 OCR 성능 확보
- 모든 시험지 포맷에 대한 범용성 보장
- 손글씨/저해상도/심한 왜곡 입력 복원
- 수식 OCR 최적화

---

## 3. 핵심 전략

1. **PDF를 먼저 분류**한다.
2. 텍스트층이 있는 PDF는 OCR보다 **레이아웃 분석을 우선**한다.
3. 시험지형 PDF는 **문제 번호(anchor)** 를 중심으로 분할한다.
4. 이미지는 독립적으로 추출하되, 최종적으로는 **문항에 귀속**시킨다.
5. LLM/OCR은 기본 경로가 아니라 **fallback**으로 사용한다.

---

## 4. 파이프라인 개요

```
PDF 입력
  ↓
[1] PDF 진단 / 페이지별 구조 분석
  ↓
[2] 페이지 유형 분류 (text-dominant / mixed-layout / image-dominant)
  ↓
[3] 레이아웃 복원 (헤더/푸터 제거, 1단/2단 판별, 컬럼 단위 블록 정렬)
  ↓
[4] 문제 번호 anchor 추출
  ↓
[5] 문항 단위 세그멘테이션 (stem / choices / assets / raw_text)
  ↓
[6] 정답/해설 페이지 별도 파싱
  ↓
[7] 문제-정답-자산 매핑
  ↓
[8] 검증 / confidence 부여
  ↓
JSON 출력
```

---

## 5. 상세 설계

### 5.1 PDF 진단 (단계 1)

페이지별 수집 메타 정보:
- 페이지 크기, 텍스트 블록 수, 텍스트 문자 수
- 이미지/벡터/도형 블록 수
- x/y 좌표 분포, 반복 헤더/푸터 후보
- 문제 번호 패턴 개수, 보기 라벨(①②③④) 출현 횟수

판별 규칙:
- **텍스트 PDF**: 추출 문자 수 threshold 이상, 텍스트 블록 충분 → 이미지가 많아도 텍스트 PDF로 간주
- **2단 구조**: 텍스트 블록 중심 x 좌표 군집화 시 2개 클러스터 존재, 또는 중앙 공백 수직 밴드 존재
- **이미지 우세**: 텍스트가 거의 없고 이미지 면적 비율이 높음 → OCR fallback 후보

### 5.2 헤더/푸터 제거 (단계 2)

설계 원칙:
- 첫 페이지와 나머지 페이지를 동일 규칙으로 처리하지 않음
- 반복 텍스트 + 반복 위치를 함께 사용
- 해당 위치 범위(band) 기준으로 제거

구현:
1. 페이지별 상단 10~15%, 하단 10~15% 영역의 텍스트 수집
2. 여러 페이지에 반복 등장하는 텍스트 탐지
3. 동일/유사 텍스트가 반복되는 y-band를 헤더/푸터 후보로 지정
4. 본문 추출 시 해당 영역 제외

### 5.3 컬럼 판별 및 분할 (단계 3)

- 1단 → 전체 영역을 하나의 컬럼으로 처리
- 2단 → left, right 컬럼 분리
- 각 컬럼 내부는 y 오름차순 정렬, 읽기 순서: left → right

판별 방법:
- **1차**: 중앙 공백 밴드 탐지
- **2차**: x-center clustering
- 둘 중 하나라도 강하게 성립하면 2단 처리

컬럼 경계: 페이지 중앙 기준 분할 + 실제 블록 분포 보정 + buffer 적용

### 5.4 문제 번호 anchor 기반 문항 세그멘테이션 (단계 4)

anchor 패턴: `r"^(\d{1,3})\.\s+"`

추출 방식:
- 각 컬럼 내 line/block 텍스트를 위→아래 순회
- 문제 번호 패턴 매칭 시 새 문항 시작점으로 간주
- 현재 anchor ~ 다음 anchor 사이 블록을 해당 문항에 귀속

주의점:
- line start 기준만 허용 (보기 숫자 혼동 방지)
- `2024.`, `1.0` 같은 표현 오탐지 방지
- anchor는 x/y 좌표와 함께 저장

### 5.5 문항 구조 파싱 (단계 5)

문항 내부 분리: stem, choices, assets, raw_text

보기 파싱 전략:
1. 문항 텍스트 전체 수집
2. 보기 라벨(①②③④) 출현 위치 탐지
3. 첫 번째 보기 라벨 전까지 → stem
4. 각 보기 라벨 사이 구간 → choice text

raw_text는 후처리/검증/LLM fallback 시 원문 보존용으로 유지

### 5.6 이미지/도형 추출 및 문항 귀속 (단계 6)

처리 단계:
1. 페이지에서 이미지/도형 객체 추출
2. 장식성/반복성 오브젝트 필터링
3. 남은 자산을 문항 구간에 매핑
4. 필요시 crop 저장

문항 귀속 조건:
- 같은 페이지, 같은 컬럼
- y 위치가 해당 문제 anchor 이후 ~ 다음 문제 anchor 이전
- 크기가 너무 작지 않음
- 헤더/푸터 영역에 속하지 않음

장식성 필터: 너무 작음(`w*h < min_area`), 페이지마다 동일 위치 반복, 헤더/푸터 영역, 얇은 선/박스/장식 도형

### 5.7 정답/해설 페이지 파싱 (단계 7)

정답 패턴: `r"(\d{1,3})\.\s*([①②③④⑤])"`

별도 파서로 처리하며, 해설 영역이 있을 경우 anchor를 추가 탐지하여 explanation 블록 추출

### 5.8 confidence / 검증 (단계 8)

confidence 감점 조건:
- 보기 4개가 비정상적으로 안 잡힘
- raw_text 길이가 비정상적으로 짧음
- 이미지가 많은데 stem이 거의 없음
- 정답 매핑 누락
- 다음 문항과 텍스트가 섞인 흔적

검증 규칙:
- 문제 번호 1~100 연속 존재 여부
- 보기 4개 비율 충분 여부
- 답안 개수 = 문제 수 일치 여부
- page/column 범위 유효성
- 이미지 bbox가 페이지 범위 내 여부

---

## 6. Fallback 전략

### 6.1 OCR fallback

기본 경로가 아님. 사용 조건:
- 텍스트 추출량이 매우 낮음
- 해당 페이지가 image-dominant로 분류됨
- 문제 번호 anchor를 전혀 찾지 못함

흐름: page rasterize → OCR → OCR text + bbox를 동일 downstream parser에 연결

### 6.2 LLM fallback

제한적 사용:
- 문항 세그멘테이션이 모호한 페이지만
- choice split 실패 문항만
- 이미지 귀속이 애매한 문항만
- 정답 페이지 파싱 실패 시 보정용

**금지**: 전체 PDF를 통째로 LLM에 넣는 것, 초기 파이프라인의 주 경로를 LLM에 의존하는 것

---

## 7. 모듈 구조

```
pdf_pipeline/
  __init__.py
  pipeline.py              # ExamPDFPipeline 메인 오케스트레이터
  types.py                 # 데이터 모델 (BBox, TextBlock, Asset, Question 등)
  config.py                # 설정값
  analyzers/
    pdf_inspector.py       # PDF 진단 (페이지별 메타 수집)
    layout_detector.py     # 레이아웃 유형 판별
    header_footer_detector.py  # 헤더/푸터 영역 탐지
    column_detector.py     # 1단/2단 판별
  extractors/
    text_extractor.py      # 텍스트 블록 추출 (읽기 순서 정렬)
    image_extractor.py     # 이미지/도형 추출
    answer_extractor.py    # 정답/해설 페이지 파싱
  segmenters/
    question_anchor_finder.py  # 문제 번호 anchor 탐지
    question_segmenter.py  # 문항 단위 분할
    choice_parser.py       # 보기 라벨 파싱
    asset_mapper.py        # 이미지 → 문항 귀속
  fallbacks/
    ocr_fallback.py        # OCR fallback
    llm_fallback.py        # LLM fallback
  validators/
    exam_validator.py      # 문항 검증
    confidence_scorer.py   # confidence 점수 부여
  utils/
    bbox.py
    regex.py
    text_normalizer.py
    debug_render.py
```

---

## 8. 데이터 모델

핵심 타입 (`types.py`):

| 클래스 | 역할 |
|--------|------|
| `BBox` | 바운딩 박스 (x0, y0, x1, y1) + width/height/area |
| `TextBlock` | 페이지/bbox/텍스트/컬럼 정보를 가진 텍스트 블록 |
| `Asset` | 이미지/벡터/테이블 자산 (페이지, bbox, 컬럼, 장식성 여부) |
| `Choice` | 보기 (label + text) |
| `Question` | 문항 (번호, 과목, stem, choices, assets, answer, confidence) |
| `PageAnalysis` | 페이지 진단 결과 (크기, 블록 수, 2단 여부, 헤더/푸터 밴드) |
| `ExamDocument` | 최종 출력 (title, source_file, questions, answers) |

---

## 9. 디버그/관측성 요구사항

중간 산출물 저장 필수:
- 페이지별 분석 결과 JSON
- 컬럼 분할 디버그 이미지
- 헤더/푸터 제거 전후 텍스트 비교
- anchor 위치 목록
- 문항별 raw_text 덤프
- asset bbox overlay 이미지
- 최종 questions.json

---

## 10. 테스트 전략

### 단위 테스트
- 문제번호 정규식, 보기 파서, 정답 파서, 헤더/푸터 필터, 컬럼 분할 판별

### 통합 테스트
- 샘플 PDF 1개 이상에 대해: 문제 수 일치, 번호 단조 증가, 답안 수 충분, 특정 문제 이미지/본문 매핑 유지

### 회귀 테스트
- 다양한 연도/회차 PDF를 fixture로 보관
- 분류: 텍스트층+2단 시험지, 텍스트층+1단 해설지, 이미지 우세, 표/그림 다수

---

## 11. 구현 시 주의사항

1. 문항 분리는 텍스트 순차 추출이 아니라 **anchor 기반**이어야 한다.
2. **2단 판별 실패**가 전체 파이프라인 품질을 가장 크게 떨어뜨린다.
3. 이미지 추출 자체보다 **문항 귀속**이 더 중요하다.
4. LLM은 주 경로가 아니라 **fallback**으로 제한해야 한다.
5. 정답 페이지는 본문과 **다른 파서**로 처리해야 한다.
6. 첫 페이지와 마지막 페이지는 일반 본문 페이지와 **동일 규칙으로 다루면 안 된다**.
