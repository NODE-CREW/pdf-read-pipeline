# PDF to Markdown 변환 계획

## 개요

시험지 PDF 문서를 마크다운 형식으로 변환하는 파이프라인을 구축합니다.
- **텍스트**: 마크다운으로 표현
- **그림/표/수식**: 이미지로 추출 후 마크다운에 이미지 경로 삽입

---

## 기술 스택

### 핵심 라이브러리

| 라이브러리 | 용도 | 버전 |
|-----------|------|------|
| `opendataloader-pdf` | PDF 파싱, 레이아웃 분석, Markdown/JSON 출력 | latest |
| `PyMuPDF (fitz)` | 이미지 추출, 페이지 렌더링 | 기존 사용 중 |
| `Pillow` | 이미지 처리 | 기존 사용 중 |

### opendataloader-pdf 주요 기능

```bash
pip install opendataloader-pdf
```

```python
import opendataloader_pdf

opendataloader_pdf.convert(
    input_path=["file1.pdf", "folder/"],
    output_dir="output/",
    format="markdown,json"
)
```

**핵심 출력 포맷**:
- **Markdown**: RAG용 구조화된 텍스트
- **JSON**: bounding box 포함, 요소별 위치 정보
  ```json
  {
    "type": "heading",
    "page number": 1,
    "bounding box": [72.0, 700.0, 540.0, 730.0],
    "content": "Introduction"
  }
  ```

**Hybrid Mode** (복잡한 PDF용):
```bash
pip install "opendataloader-pdf[hybrid]"
opendataloader-pdf-hybrid --port 5002
opendataloader-pdf --hybrid docling-fast file1.pdf
```

**지원 기능**:
- OCR (80+ 언어, 한국어 `ko` 포함)
- 수식 추출 (LaTeX)
- 차트/이미지 설명 생성
- 테이블 추출

---

## 아키텍처

```
┌─────────────────────────────────────────────────────────────┐
│                        입력: PDF 파일                        │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│              1단계: PDF 파싱 (opendataloader-pdf)            │
│  - 레이아웃 분석                                             │
│  - 요소 분류 (heading, paragraph, table, picture, formula)  │
│  - bounding box 추출                                        │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    2단계: 요소 분류 처리                      │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐          │
│  │   텍스트    │  │  표/그림    │  │    수식     │          │
│  │  → MD 변환  │  │ → 이미지    │  │ → LaTeX/IMG │          │
│  └─────────────┘  └─────────────┘  └─────────────┘          │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                   3단계: 이미지 추출/저장                     │
│  - 표/그림/차트 → PNG 파일로 추출                            │
│  - 저장 경로: output/<pdf_name>/images/                     │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                 4단계: 마크다운 문서 조립                     │
│  - 텍스트 요소 → 마크다운 텍스트                             │
│  - 이미지 요소 → ![alt](./images/xxx.png)                   │
│  - 수식 → $LaTeX$ 또는 이미지                               │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      출력: Markdown 파일                     │
│  output/<pdf_name>/                                         │
│    ├── document.md                                          │
│    ├── images/                                              │
│    │   ├── table_001.png                                    │
│    │   ├── figure_002.png                                   │
│    │   └── ...                                              │
│    └── metadata.json                                        │
└─────────────────────────────────────────────────────────────┘
```

---

## 출력 구조

```
output/<pdf_name>/
├── document.md           # 최종 마크다운 문서
├── questions/            # 문항별 분리 (시험지 특화)
│   ├── q001.md
│   ├── q002.md
│   └── ...
├── images/               # 추출된 이미지
│   ├── table_p01_001.png
│   ├── figure_p02_001.png
│   ├── formula_p03_001.png
│   └── ...
├── raw_json/             # opendataloader 원본 출력
│   └── elements.json
└── metadata.json         # 변환 메타데이터
```

---

## 마크다운 출력 예시

```markdown
# 제1문

다음 글을 읽고 물음에 답하시오.

![지문 이미지](./images/passage_001.png)

## 문제 1

다음 중 옳은 것은?

① 선택지 1
② 선택지 2
③ 선택지 3
④ 선택지 4
⑤ 선택지 5

![문제 그림](./images/figure_001.png)

---

## 문제 2

아래 표를 보고 답하시오.

![표](./images/table_001.png)

수식: $\frac{x+y}{2}$
```

---

## 세부 구현 사항

### 1. 요소 타입별 처리 전략

| 요소 타입 | opendataloader 타입 | 처리 방법 |
|-----------|---------------------|-----------|
| 제목 | `heading` | `# 제목` (level에 따라 `#` 개수 조정) |
| 본문 | `paragraph` | 그대로 텍스트 |
| 표 | `table` | 이미지 추출 → `![표](./images/table_xxx.png)` |
| 그림 | `picture` | 이미지 추출 → `![그림](./images/figure_xxx.png)` |
| 수식 | `formula` | LaTeX 사용 가능 시 `$latex$`, 복잡하면 이미지 |
| 리스트 | `list` | 마크다운 리스트 (`-` 또는 `1.`) |

### 2. 이미지 추출 조건

이미지로 추출해야 하는 경우:
- `type: "table"` — 모든 표
- `type: "picture"` — 모든 그림/차트
- `type: "formula"` — 복잡한 수식 (inline LaTeX 불가 시)
- 텍스트 인식 실패 영역 — OCR 결과가 빈약할 때

### 3. 이미지 파일명 규칙

```
<type>_p<page>_<index>.png
```

예시:
- `table_p01_001.png` — 1페이지 첫 번째 표
- `figure_p02_003.png` — 2페이지 세 번째 그림
- `formula_p05_001.png` — 5페이지 첫 번째 수식

### 4. 기존 파이프라인과 통합

현재 `pipelines/base.py`의 문항 경계 추정 로직을 재사용:
- 문항 시작 패턴: `문 1`, `제 1 문`, `1.`, `1)` 등
- 선택지 패턴: `①~⑩`, `(1)~(5)` 등

---

## Todo 체크리스트

### Phase 1: 환경 구축 및 기초 테스트

- [ ] **1.1** opendataloader-pdf 설치 및 기본 동작 확인
  ```bash
  pip install opendataloader-pdf
  ```
- [ ] **1.2** 샘플 PDF로 Markdown/JSON 출력 테스트
  ```python
  opendataloader_pdf.convert(
      input_path=["tiger/sample/comh1_040215.pdf"],
      output_dir="output/test_odl/",
      format="markdown,json"
  )
  ```
- [ ] **1.3** 출력 JSON 구조 분석 및 요소 타입 확인
- [ ] **1.4** Hybrid mode 설치 및 OCR/수식 추출 테스트 (선택)
  ```bash
  pip install "opendataloader-pdf[hybrid]"
  ```

### Phase 2: 이미지 추출 모듈 개발

- [ ] **2.1** JSON 요소에서 이미지 대상 필터링 함수 작성
  - 입력: JSON 요소 리스트
  - 출력: `table`, `picture`, `formula` 타입 요소 리스트
- [ ] **2.2** bounding box 기반 이미지 crop 함수 작성
  - 입력: PDF 페이지, bounding box `[left, bottom, right, top]`
  - 출력: PIL Image
- [ ] **2.3** 이미지 저장 함수 작성
  - 파일명 규칙 적용
  - 저장 경로 관리
- [ ] **2.4** 단위 테스트 작성

### Phase 3: 마크다운 조립 모듈 개발

- [ ] **3.1** JSON 요소 → 마크다운 변환 함수 작성
  - `heading` → `# 제목`
  - `paragraph` → 텍스트
  - `list` → 마크다운 리스트
- [ ] **3.2** 이미지 요소 → 마크다운 이미지 참조 삽입
  - `![alt](./images/xxx.png)`
- [ ] **3.3** 요소 순서 정렬 (reading order 기반)
- [ ] **3.4** 마크다운 문서 조립 및 파일 저장
- [ ] **3.5** 단위 테스트 작성

### Phase 4: 시험지 특화 처리

- [ ] **4.1** 기존 문항 경계 추정 로직 통합
  - `pipelines/base.py` 재사용
- [ ] **4.2** 문항별 마크다운 분리 저장
  - `questions/q001.md`, `q002.md`, ...
- [ ] **4.3** 공통 지문 처리
- [ ] **4.4** 단위 테스트 작성

### Phase 5: 통합 및 CLI

- [ ] **5.1** 전체 파이프라인 통합
  - PDF → opendataloader → 이미지 추출 → 마크다운 조립
- [ ] **5.2** CLI 스크립트 작성
  ```bash
  python pdf_to_markdown.py --pdf input.pdf --output-dir output/
  ```
- [ ] **5.3** 배치 처리 지원
- [ ] **5.4** 에러 핸들링 및 로깅
- [ ] **5.5** 통합 테스트 작성
- [ ] **5.6** README.md 업데이트

### Phase 6: 품질 개선 (선택)

- [ ] **6.1** Hybrid mode OCR 적용 (스캔본 PDF)
- [ ] **6.2** 수식 LaTeX 추출 및 inline 삽입
- [ ] **6.3** 이미지 품질 최적화 (해상도, 압축)
- [ ] **6.4** 테이블 구조 마크다운 변환 시도

---

## 의존성 요구사항

### requirements.txt 추가 항목

```
opendataloader-pdf>=0.x.x
```

### Hybrid mode (선택)

```
opendataloader-pdf[hybrid]>=0.x.x
```

### 시스템 요구사항

- **Java 11+** (opendataloader-pdf 필수)
  ```bash
  java -version
  ```
- **Python 3.10+**

---

## 참고 자료

- [opendataloader-pdf GitHub](https://github.com/opendataloader-project/opendataloader-pdf)
- [opendataloader-pdf JSON Schema](https://opendataloader.org/docs/json-schema)
- [Hybrid Mode Guide](https://opendataloader.org/docs/hybrid-mode)
- 기존 프로젝트 `pipelines/base.py` — 문항 경계 추정 로직

---

## 리스크 및 고려사항

1. **Java 의존성**: opendataloader-pdf는 Java 11+ 필요
2. **Hybrid mode 서버**: 복잡한 PDF 처리 시 별도 서버 프로세스 필요
3. **레이아웃 정확도**: 시험지 특수 레이아웃에서 정확도 검증 필요
4. **기존 파이프라인 호환**: 현재 `pipelines/` 구조와 충돌 없이 통합해야 함
