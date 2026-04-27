# 시험지형 PDF 파싱 — 실행 태스크 목록

## Phase 1: 핵심 파싱 파이프라인

> PDF 진단 → 레이아웃 복원 → 문항 분리 → 정답 파싱까지의 최소 기능 구현

> 진행 메모 (2026-04-22): 계획서에 적힌 `pdf_pipeline/...` 세부 모듈 구조 대신, 현재는 `pipelines/exam_pdf.py`와 `11_run_exam_pdf_pipeline.py`에 Phase 1 핵심 기능을 통합 구현했다. 체크된 항목은 현재 코드/테스트로 직접 확인된 범위만 반영한다.

### 1.1 프로젝트 세팅
- [ ] `pdf_pipeline/` 디렉토리 구조 생성 (`__init__.py`, `types.py`, `config.py`, `pipeline.py`)
- [ ] `types.py` 데이터 모델 작성 (`BBox`, `TextBlock`, `Asset`, `Choice`, `Question`, `PageAnalysis`, `ExamDocument`)
- [x] 의존성 확인 (`PyMuPDF/fitz` 등)

### 1.2 PDF 진단기
- [ ] `analyzers/pdf_inspector.py` — 페이지별 메타 수집 (텍스트/이미지/벡터 블록 수, 문자 수, 텍스트 우세 여부)
- [ ] 단위 테스트: 텍스트 PDF 판별, 이미지 우세 판별

### 1.3 헤더/푸터 제거
- [ ] `analyzers/header_footer_detector.py` — 상단/하단 band 기반 헤더/푸터 영역 탐지
- [ ] 첫 페이지 / 일반 페이지 별도 비율 적용
- [ ] 단위 테스트: 헤더/푸터 band 계산 검증

### 1.4 2단 판별
- [ ] `analyzers/column_detector.py` — 중앙 공백 밴드 탐지 + x-center clustering
- [x] 단위 테스트: 2단 시험지 vs 1단 해설지 판별

### 1.5 텍스트 추출
- [ ] `extractors/text_extractor.py` — 헤더/푸터 제거 후 컬럼 단위 텍스트 블록 추출, 읽기 순서 정렬
- [ ] 단위 테스트: 읽기 순서가 left→right, 위→아래 순서인지 검증

### 1.6 문제 번호 anchor 추출
- [ ] `segmenters/question_anchor_finder.py` — `r"^(\d{1,3})\.\s+"` 패턴으로 anchor 탐지
- [ ] 단위 테스트: `1. 문제 본문 ...` → anchor 검출, 오탐지(`2024.`, `1.0`) 방지

### 1.7 문항 분리
- [ ] `segmenters/question_segmenter.py` — anchor 기반 문항 단위 세그멘테이션
- [ ] `segmenters/choice_parser.py` — 보기 라벨(①②③④) 파싱, stem/choices 분리
- [x] 단위 테스트: `① A ② B ③ C ④ D` → choices 4개 검출

### 1.8 정답 페이지 파싱
- [ ] `extractors/answer_extractor.py` — 정답 페이지 탐지 + `r"(\d{1,3})\.\s*([①②③④⑤])"` 패턴 매칭
- [x] 단위 테스트: `1.① 2.③` → answer map 생성

### 1.9 파이프라인 통합
- [x] `pipeline.py` — `ExamPDFPipeline.run()` 메인 오케스트레이터 작성 (`pipelines/exam_pdf.py`에 통합 구현)
- [x] 샘플 PDF 1개로 end-to-end 실행 확인
- [x] 통합 테스트: 문제 수, 번호 단조 증가, 답안 수 검증

---

## Phase 2: 자산 관리 및 검증

> 이미지 추출/문항 귀속, confidence scoring, 디버그 아티팩트

### 2.1 이미지 추출
- [ ] `extractors/image_extractor.py` — 페이지별 이미지/도형 객체 추출, 장식성 필터링
- [ ] 이미지 crop 및 파일 저장 (`assets/` 디렉토리)

### 2.2 이미지 → 문항 귀속
- [ ] `segmenters/asset_mapper.py` — 페이지/컬럼/y위치 기준 문항 매핑
- [ ] 단위 테스트: 특정 이미지가 올바른 문항에 귀속되는지 검증

### 2.3 Confidence Scoring
- [ ] `validators/confidence_scorer.py` — 보기 수, stem 유무, raw_text 길이, 정답 매핑 여부 기반 점수 부여
- [ ] 단위 테스트: 다양한 조건별 점수 검증

### 2.4 검증기
- [ ] `validators/exam_validator.py` — 문제 번호 연속성, 중복 검사, 답안 수 일치, bbox 범위 유효성
- [ ] 단위 테스트

### 2.5 디버그 아티팩트 저장
- [ ] 페이지별 분석 결과 JSON 저장
- [ ] 컬럼 분할 디버그 이미지 생성
- [ ] 헤더/푸터 제거 전후 텍스트 비교 저장
- [ ] anchor 위치 목록 저장
- [ ] 문항별 raw_text 덤프
- [ ] asset bbox overlay 이미지
- [ ] 최종 `questions.json` 출력

---

## Phase 3: Fallback 및 확장

> OCR/LLM fallback, 과목 자동 인식, 해설 정교화

### 3.1 OCR fallback
- [ ] `fallbacks/ocr_fallback.py` — image-dominant 페이지 rasterize → OCR → downstream parser 연결
- [ ] 사용 조건: 텍스트 추출량 극소, image-dominant 분류, anchor 전혀 없음

### 3.2 LLM fallback
- [ ] `fallbacks/llm_fallback.py` — 세그멘테이션 모호/choice split 실패/이미지 귀속 애매한 문항 대상
- [ ] 전체 PDF를 LLM에 넣지 않음 (문항 단위로만)

### 3.3 과목(subject) 자동 인식
- [x] 과목 경계 패턴 탐지 → 문항별 subject 필드 자동 부여

### 3.4 해설 텍스트 정교화
- [ ] 해설 영역 anchor 탐지 → 문항별 explanation 블록 추출

---

## 회귀 테스트 fixture

- [ ] 텍스트층 + 2단 시험지 PDF 확보
- [ ] 텍스트층 + 1단 해설지 PDF 확보
- [ ] 이미지 우세 PDF 확보
- [ ] 표/그림이 많은 PDF 확보

---

## 작업 순서 요약

```
1. 저장소 기존 PDF 파싱 진입점 확인
2. PDF 전처리 레이어 추가 위치 식별
3. analyzers / extractors / segmenters / validators 모듈 추가
4. 최소 기능 구현 (Phase 1): 2단 판별 → 헤더/푸터 → anchor → 정답
5. 샘플 PDF로 중간 결과 디버그 파일 저장
6. 문항 수 / 정답 수 / 누락 문항 점검
7. 이미지 귀속 (Phase 2)
8. 실패 문항 수집 → fallback 대상 분류 (Phase 3)
```
