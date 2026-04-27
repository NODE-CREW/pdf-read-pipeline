아래에 바로 붙여서 쓸 수 있는 마크다운 문서 초안으로 정리했습니다.
파일로 저장까지 하려 했는데 현재 도구 실행 오류가 나서, 문서는 본문으로 제공합니다.

# 시험지형 PDF 파싱 개선 설계안
## 문서 목적
이 문서는 **시험지형 PDF(특히 2단 구조 + 텍스트층 존재 + 도형/이미지 혼합)** 를 안정적으로 파싱하여,
최종적으로 **문제 / 보기 / 정답 / 해설 / 이미지 매핑** 구조의 JSON 데이터로 변환하기 위한 설계안과 코드 골격을 정의한다.
대상 독자는 구현 Agent이며, 이 문서를 기준으로 저장소 내 파이프라인을 수정하거나 신규 모듈을 추가할 수 있어야 한다.
---
## 1. 문제 정의
현재 `opendataloader` 기반 PDF 변환은 다음과 같은 유형에서 실패 가능성이 높다.
- 텍스트층은 존재하지만 레이아웃이 단순하지 않은 PDF
- 2단 시험지 레이아웃
- 페이지 상/하단 헤더, 푸터, 저작권 박스, 과목명, 페이지 번호가 섞인 PDF
- 문제 본문 중간에 이미지/도형이 포함된 PDF
- 문제 단위가 페이지/단(column) 경계를 넘는 PDF
이번 입력 PDF는 다음 특성을 가진다.
- 텍스트 추출은 가능함
- 시험지 본문은 **2단 구조**
- 시각 요소(이미지/벡터/도형)가 섞여 있음
- 마지막 페이지에 **정답/해설 텍스트**가 존재함
- 단순 page-order 텍스트 추출만으로는 읽기 순서가 깨질 수 있음
즉, 이 문제의 본질은 OCR 부재가 아니라 **레이아웃 복원 및 문항 단위 세그멘테이션 실패**이다.
---
## 2. 목표
### 2.1 MVP 목표
다음 구조의 데이터를 안정적으로 생성한다.
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
          "bbox": [x0, y0, x1, y1],
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

2.2 비목표

초기 단계에서는 다음은 제외한다.

* 완전 스캔형 이미지 PDF에 대한 최고 수준 OCR 성능 확보
* 모든 시험지 포맷에 대한 범용성 보장
* 손글씨/저해상도/심한 왜곡 입력 복원
* 수식 OCR 최적화

⸻

3. 핵심 전략

3.1 전체 방향

기존처럼 PDF 전체를 순차적으로 읽지 않고, 먼저 PDF 구조를 진단한 후 결과에 따라 분기한다.

핵심 원칙은 다음과 같다.

1. PDF를 먼저 분류한다.
2. 텍스트층이 있는 PDF는 OCR보다 레이아웃 분석을 우선한다.
3. 시험지형 PDF는 문제 번호(anchor) 를 중심으로 분할한다.
4. 이미지는 독립적으로 추출하되, 최종적으로는 문항에 귀속시킨다.
5. LLM/OCR은 기본 경로가 아니라 fallback 으로 사용한다.

⸻

4. 파이프라인 개요

PDF 입력
  ↓
[1] PDF 진단 / 페이지별 구조 분석
  ↓
[2] 페이지 유형 분류
    - text-dominant
    - mixed-layout
    - image-dominant
  ↓
[3] 레이아웃 복원
    - 헤더/푸터 제거
    - 1단/2단 판별
    - 컬럼 단위 블록 정렬
  ↓
[4] 문제 번호 anchor 추출
    - 1., 2., 3. ...
  ↓
[5] 문항 단위 세그멘테이션
    - stem / choices / assets / raw_text
  ↓
[6] 정답/해설 페이지 별도 파싱
  ↓
[7] 문제-정답-자산 매핑
  ↓
[8] 검증 / confidence 부여
  ↓
JSON 출력

⸻

5. 상세 설계

5.1 단계 1: PDF 진단

각 페이지에 대해 아래 특징량을 계산한다.

수집할 메타 정보

* 페이지 크기 (width, height)
* 텍스트 블록 수
* 텍스트 문자 수
* 이미지 블록 수
* 벡터/도형 블록 수
* x 좌표 분포
* y 좌표 분포
* 반복 헤더/푸터 후보 텍스트
* 문제 번호 패턴 개수
* 보기 라벨(① ② ③ ④) 출현 횟수

판별 목적

* 텍스트층이 충분한가?
* 2단 구조인가?
* 본문 외 장식 요소가 많은가?
* OCR fallback 이 필요한가?

추천 판별 규칙

텍스트 PDF 여부

* 추출 문자 수가 threshold 이상
* 텍스트 블록 수가 충분
* 이미지가 많아도 텍스트층이 살아 있으면 텍스트 PDF로 간주

2단 구조 여부

* 텍스트 블록 중심 x 좌표를 군집화했을 때 2개의 주요 클러스터가 존재
* 혹은 페이지 중앙 근처에 공백 수직 밴드가 있음

이미지 우세 페이지 여부

* 텍스트가 거의 없고 이미지 면적 비율이 높음
* 이 경우 OCR fallback 후보

⸻

5.2 단계 2: 헤더/푸터 제거

시험지 PDF에는 반복적인 비본문 요소가 많다.

예시:

* 회1
* - 1 -, - 2 -
* 제 1 과목 ...
* 저작권 안내
* 상단 배너 문구

설계 원칙

* 첫 페이지와 나머지 페이지를 동일 규칙으로 처리하지 않는다.
* 반복 텍스트 + 반복 위치를 함께 사용한다.
* 제거는 텍스트만이 아니라 해당 위치 범위(band) 기준으로 한다.

구현 아이디어

1. 페이지별 상단 1015%, 하단 1015% 영역의 텍스트를 수집
2. 여러 페이지에 반복 등장하는 텍스트를 찾음
3. 동일/유사 텍스트가 반복되는 y-band를 헤더/푸터 후보로 지정
4. 본문 추출 시 해당 영역 제외

주의점

* 첫 페이지의 제목 영역은 반복되지 않을 수 있음
* 정답/해설 페이지는 구조가 다를 수 있으므로 별도 규칙 허용

⸻

5.3 단계 3: 컬럼(1단/2단) 판별 및 분할

이 단계는 본 설계의 핵심이다.

목표

텍스트/이미지 블록을 페이지 단위가 아니라 컬럼 단위 읽기 순서로 재배치한다.

기본 규칙

* 1단 페이지면 전체 영역을 하나의 컬럼으로 처리
* 2단 페이지면 left, right 컬럼으로 분리
* 각 컬럼 내부는 y 오름차순 정렬
* 최종 읽기 순서는 left → right

컬럼 판별 방법

방법 A. x-좌표 기반 clustering

텍스트 블록들의 중심 x값을 사용하여 2개의 주요 군집 존재 여부를 판단한다.

방법 B. 중앙 공백 밴드 탐지

페이지 중앙 근처에 텍스트/이미지 블록이 거의 없는 수직 영역이 존재하면 2단 가능성이 높다.

권장

* 1차: 중앙 공백 밴드 탐지
* 2차: x-center clustering
* 둘 중 하나라도 강하게 성립하면 2단으로 처리

컬럼 경계 산출

* 페이지 중앙 기준으로 분할하되
* 실제 블록 분포를 보고 margin 보정
* 중앙에서 약간의 buffer를 둬서 양 컬럼 블록 겹침 방지

⸻

5.4 단계 4: 문제 번호(anchor) 기반 문항 세그멘테이션

문항 분리 기준은 문제 번호 패턴이다.

anchor 패턴

정규식 예시:

r"^(\d{1,3})\.\s+"

추가 후보:

* 1.
* 23.
* OCR fallback 시 1 ), 1) 도 일부 허용 가능

anchor 추출 방식

* 각 컬럼 내 line/block 텍스트를 위에서 아래로 순회
* 문제 번호 패턴이 매칭되면 새 문항 시작점으로 간주
* 현재 anchor와 다음 anchor 사이의 블록들을 해당 문항에 귀속

주의점

* 보기 숫자와 혼동하지 않도록 line start 기준만 허용
* 본문 중 2024., 1.0 같은 숫자 표현 오탐지 방지 필요
* anchor는 x/y 좌표와 함께 저장

⸻

5.5 단계 5: 문항 구조 파싱

문항 내부에서 다음 요소를 분리한다.

* stem(문제 본문)
* choices(보기)
* assets(이미지/도형)
* raw_text

보기 파싱

보기 라벨은 보통 다음 패턴을 사용한다.

* ①, ②, ③, ④
* 일부 문항은 가로 배치될 수 있음

권장 전략

1. 문항 텍스트 전체를 수집
2. 보기 라벨 출현 위치를 찾음
3. 첫 번째 보기 라벨 전까지는 stem
4. 각 보기 라벨 사이 구간을 choice text로 파싱

예외

* 보기 없는 문항
* 표/그림을 포함한 문항
* 보기 라벨이 줄바꿈으로 분리된 문항

raw_text 유지 이유

후처리/검증/LLM fallback 시 원문 보존이 필요하다.

⸻

5.6 단계 6: 이미지/도형 추출 및 문항 귀속

문제

PDF 내부의 이미지/도형은 단순히 추출만 해서는 가치가 낮다.
중요한 것은 어느 문제에 속하는가 이다.

처리 단계

1. 페이지에서 이미지/도형 객체를 추출
2. 장식성/반복성 오브젝트 필터링
3. 남은 자산을 문항 구간에 매핑
4. 필요시 crop 저장

문항 귀속 규칙

어떤 asset이 다음 조건을 만족하면 해당 문항에 연결한다.

* 같은 페이지에 있음
* 같은 컬럼에 있음
* y 위치가 해당 문제 anchor 이후 ~ 다음 문제 anchor 이전 구간에 있음
* 크기가 너무 작지 않음
* 헤더/푸터 영역에 속하지 않음

장식성 오브젝트 필터 예시

* 너무 작음 (w*h < min_area)
* 페이지마다 동일 위치 반복
* 헤더/푸터 영역에 위치
* 얇은 선, 박스, 장식 도형

저장 형식

{
  "type": "image",
  "page": 1,
  "column": "right",
  "bbox": [304, 264, 560, 420],
  "path": "assets/q008_img01.png"
}

⸻

5.7 단계 7: 정답/해설 페이지 별도 파싱

마지막 페이지에는 정답 및 해설 형식으로 번호-답이 존재할 수 있다.
이 영역은 일반 문항 파서로 처리하지 말고 별도 파서로 처리한다.

예시 패턴

* 1.① 2.③ 3.② ...
* 81.① 82.① ...

정답 파서 전략

정규식 예시:

r"(\d{1,3})\.\s*([①②③④⑤])"

결과 예시

{
  "1": "①",
  "2": "③",
  "3": "②"
}

해설이 별도 텍스트로 있을 경우

* 해설 영역 anchor를 추가로 탐지
* 문제 번호 기준으로 explanation 블록 추출
* 초기에는 없어도 괜찮음

⸻

5.8 단계 8: confidence / 검증

각 문항에 confidence score를 부여한다.

confidence를 낮추는 조건 예시

* 문제번호 anchor는 있는데 보기 4개가 비정상적으로 안 잡힘
* raw_text 길이가 비정상적으로 짧음
* 이미지가 많은데 stem이 거의 없음
* 정답 매핑 누락
* 다음 문항과 텍스트가 섞인 흔적 존재

검증 규칙 예시

* 문제 번호가 1~100 연속적으로 존재하는가
* 보기 4개 비율이 충분한가
* 답안 개수가 문제 수와 일치하는가
* 각 문항의 page/column 범위가 유효한가
* 이미지 bbox가 페이지 범위를 벗어나지 않는가

⸻

6. Fallback 전략

6.1 OCR fallback

OCR은 기본 경로가 아니다. 다음 경우만 사용한다.

* 텍스트 추출량이 매우 낮음
* 해당 페이지가 image-dominant 로 분류됨
* 문제 번호 anchor를 전혀 찾지 못함

권장 흐름

* page rasterize
* OCR 수행
* OCR text + bbox를 동일한 downstream parser 에 연결

6.2 LLM fallback

LLM은 다음처럼 제한적으로 사용한다.

* 문항 세그멘테이션이 모호한 페이지만
* choice split 실패 문항만
* 이미지 귀속이 애매한 문항만
* 정답 페이지 파싱 실패 시 보정용

절대 금지

* 전체 PDF를 통째로 LLM에 넣어서 구조화를 맡기는 것
* 초기 파이프라인의 주 경로를 LLM에 의존하는 것

이유:

* 비용 증가
* 재현성 하락
* 디버깅 난이도 증가

⸻

7. 저장소 반영 방향

7.1 제안 모듈 구조

pdf_pipeline/
  __init__.py
  pipeline.py
  types.py
  config.py
  analyzers/
    pdf_inspector.py
    layout_detector.py
    header_footer_detector.py
    column_detector.py
  extractors/
    text_extractor.py
    image_extractor.py
    answer_extractor.py
  segmenters/
    question_anchor_finder.py
    question_segmenter.py
    choice_parser.py
    asset_mapper.py
  fallbacks/
    ocr_fallback.py
    llm_fallback.py
  validators/
    exam_validator.py
    confidence_scorer.py
  utils/
    bbox.py
    regex.py
    text_normalizer.py
    debug_render.py

⸻

8. 데이터 모델 초안

8.1 types.py

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal, Optional
ColumnName = Literal["full", "left", "right"]
AssetType = Literal["image", "vector", "table"]
@dataclass
class BBox:
    x0: float
    y0: float
    x1: float
    y1: float
    @property
    def width(self) -> float:
        return self.x1 - self.x0
    @property
    def height(self) -> float:
        return self.y1 - self.y0
    @property
    def area(self) -> float:
        return self.width * self.height
@dataclass
class TextBlock:
    page_no: int
    bbox: BBox
    text: str
    block_no: int
    line_no: int | None = None
    column: ColumnName = "full"
@dataclass
class Asset:
    page_no: int
    bbox: BBox
    asset_type: AssetType
    path: Optional[str] = None
    column: ColumnName = "full"
    is_decorative: bool = False
@dataclass
class Choice:
    label: str
    text: str
@dataclass
class Question:
    question_no: int
    subject: Optional[str]
    stem: str
    choices: list[Choice] = field(default_factory=list)
    assets: list[Asset] = field(default_factory=list)
    answer: Optional[str] = None
    explanation: Optional[str] = None
    raw_text: str = ""
    pages: list[int] = field(default_factory=list)
    columns: list[ColumnName] = field(default_factory=list)
    confidence: float = 0.0
@dataclass
class PageAnalysis:
    page_no: int
    width: float
    height: float
    text_char_count: int
    text_block_count: int
    image_block_count: int
    vector_block_count: int
    is_text_dominant: bool
    is_two_column: bool
    header_band: Optional[BBox] = None
    footer_band: Optional[BBox] = None
@dataclass
class ExamDocument:
    title: Optional[str]
    source_file: str
    questions: list[Question] = field(default_factory=list)
    answers: dict[int, str] = field(default_factory=dict)

⸻

9. 핵심 컴포넌트 코드 골격

9.1 pipeline.py

from __future__ import annotations
from pdf_pipeline.analyzers.pdf_inspector import PDFInspector
from pdf_pipeline.analyzers.header_footer_detector import HeaderFooterDetector
from pdf_pipeline.analyzers.column_detector import ColumnDetector
from pdf_pipeline.extractors.text_extractor import TextExtractor
from pdf_pipeline.extractors.image_extractor import ImageExtractor
from pdf_pipeline.extractors.answer_extractor import AnswerExtractor
from pdf_pipeline.segmenters.question_anchor_finder import QuestionAnchorFinder
from pdf_pipeline.segmenters.question_segmenter import QuestionSegmenter
from pdf_pipeline.segmenters.asset_mapper import AssetMapper
from pdf_pipeline.validators.exam_validator import ExamValidator
from pdf_pipeline.validators.confidence_scorer import ConfidenceScorer
from pdf_pipeline.types import ExamDocument
class ExamPDFPipeline:
    def __init__(self) -> None:
        self.inspector = PDFInspector()
        self.header_footer_detector = HeaderFooterDetector()
        self.column_detector = ColumnDetector()
        self.text_extractor = TextExtractor()
        self.image_extractor = ImageExtractor()
        self.answer_extractor = AnswerExtractor()
        self.anchor_finder = QuestionAnchorFinder()
        self.question_segmenter = QuestionSegmenter()
        self.asset_mapper = AssetMapper()
        self.validator = ExamValidator()
        self.confidence_scorer = ConfidenceScorer()
    def run(self, pdf_path: str) -> ExamDocument:
        page_analyses = self.inspector.inspect(pdf_path)
        page_analyses = self.header_footer_detector.detect(pdf_path, page_analyses)
        page_analyses = self.column_detector.detect(pdf_path, page_analyses)
        text_blocks = self.text_extractor.extract(pdf_path, page_analyses)
        assets = self.image_extractor.extract(pdf_path, page_analyses)
        anchors = self.anchor_finder.find(text_blocks)
        questions = self.question_segmenter.segment(text_blocks, anchors)
        questions = self.asset_mapper.map(questions, assets)
        answers = self.answer_extractor.extract(pdf_path, page_analyses)
        for q in questions:
            q.answer = answers.get(q.question_no)
        questions = self.confidence_scorer.score(questions)
        self.validator.validate(questions, answers)
        return ExamDocument(
            title=None,
            source_file=pdf_path,
            questions=questions,
            answers=answers,
        )

9.2 analyzers/pdf_inspector.py

from __future__ import annotations
import fitz
from pdf_pipeline.types import PageAnalysis
class PDFInspector:
    def inspect(self, pdf_path: str) -> list[PageAnalysis]:
        doc = fitz.open(pdf_path)
        results: list[PageAnalysis] = []
        for page_index in range(len(doc)):
            page = doc[page_index]
            text_dict = page.get_text("dict")
            text_char_count = 0
            text_block_count = 0
            image_block_count = 0
            vector_block_count = 0
            for block in text_dict.get("blocks", []):
                block_type = block.get("type", 0)
                if block_type == 0:
                    text_block_count += 1
                    for line in block.get("lines", []):
                        for span in line.get("spans", []):
                            text_char_count += len(span.get("text", ""))
                elif block_type == 1:
                    image_block_count += 1
            is_text_dominant = text_char_count > 100
            results.append(
                PageAnalysis(
                    page_no=page_index + 1,
                    width=page.rect.width,
                    height=page.rect.height,
                    text_char_count=text_char_count,
                    text_block_count=text_block_count,
                    image_block_count=image_block_count,
                    vector_block_count=vector_block_count,
                    is_text_dominant=is_text_dominant,
                    is_two_column=False,
                )
            )
        return results

9.3 analyzers/header_footer_detector.py

from __future__ import annotations
import fitz
from pdf_pipeline.types import BBox, PageAnalysis
class HeaderFooterDetector:
    def detect(self, pdf_path: str, pages: list[PageAnalysis]) -> list[PageAnalysis]:
        doc = fitz.open(pdf_path)
        for page_analysis in pages:
            page = doc[page_analysis.page_no - 1]
            height = page.rect.height
            if page_analysis.page_no == 1:
                header_ratio = 0.10
                footer_ratio = 0.05
            else:
                header_ratio = 0.07
                footer_ratio = 0.05
            page_analysis.header_band = BBox(0, 0, page.rect.width, height * header_ratio)
            page_analysis.footer_band = BBox(0, height * (1 - footer_ratio), page.rect.width, height)
        return pages

9.4 analyzers/column_detector.py

from __future__ import annotations
import fitz
from pdf_pipeline.types import PageAnalysis
class ColumnDetector:
    def detect(self, pdf_path: str, pages: list[PageAnalysis]) -> list[PageAnalysis]:
        doc = fitz.open(pdf_path)
        for page_analysis in pages:
            page = doc[page_analysis.page_no - 1]
            blocks = page.get_text("blocks")
            width = page.rect.width
            center = width / 2
            left_count = 0
            right_count = 0
            center_band_count = 0
            for block in blocks:
                x0, y0, x1, y1, text, *_ = block
                if not str(text).strip():
                    continue
                block_center = (x0 + x1) / 2
                if center - width * 0.08 <= block_center <= center + width * 0.08:
                    center_band_count += 1
                elif block_center < center:
                    left_count += 1
                else:
                    right_count += 1
            page_analysis.is_two_column = (
                left_count > 5 and right_count > 5 and center_band_count < max(3, (left_count + right_count) * 0.15)
            )
        return pages

9.5 extractors/text_extractor.py

from __future__ import annotations
import fitz
from pdf_pipeline.types import BBox, PageAnalysis, TextBlock
class TextExtractor:
    def extract(self, pdf_path: str, page_analyses: list[PageAnalysis]) -> list[TextBlock]:
        doc = fitz.open(pdf_path)
        results: list[TextBlock] = []
        page_analysis_map = {p.page_no: p for p in page_analyses}
        for page_no, page_analysis in page_analysis_map.items():
            page = doc[page_no - 1]
            blocks = page.get_text("blocks")
            page_width = page.rect.width
            center = page_width / 2
            for idx, block in enumerate(blocks):
                x0, y0, x1, y1, text, *_ = block
                text = str(text).strip()
                if not text:
                    continue
                bbox = BBox(x0, y0, x1, y1)
                if self._is_in_header_footer(bbox, page_analysis):
                    continue
                column = "full"
                if page_analysis.is_two_column:
                    block_center = (x0 + x1) / 2
                    column = "left" if block_center < center else "right"
                results.append(
                    TextBlock(
                        page_no=page_no,
                        bbox=bbox,
                        text=text,
                        block_no=idx,
                        column=column,
                    )
                )
        return self._sort_reading_order(results)
    def _is_in_header_footer(self, bbox: BBox, page_analysis: PageAnalysis) -> bool:
        if page_analysis.header_band and bbox.y1 <= page_analysis.header_band.y1:
            return True
        if page_analysis.footer_band and bbox.y0 >= page_analysis.footer_band.y0:
            return True
        return False
    def _sort_reading_order(self, blocks: list[TextBlock]) -> list[TextBlock]:
        column_order = {"full": 0, "left": 0, "right": 1}
        return sorted(blocks, key=lambda b: (b.page_no, column_order[b.column], b.bbox.y0, b.bbox.x0))

9.6 segmenters/question_anchor_finder.py

from __future__ import annotations
import re
from dataclasses import dataclass
from pdf_pipeline.types import ColumnName, TextBlock
ANCHOR_RE = re.compile(r"^(\d{1,3})\.\s+")
@dataclass
class QuestionAnchor:
    question_no: int
    page_no: int
    column: ColumnName
    block_index: int
class QuestionAnchorFinder:
    def find(self, blocks: list[TextBlock]) -> list[QuestionAnchor]:
        anchors: list[QuestionAnchor] = []
        for i, block in enumerate(blocks):
            text = block.text.strip()
            match = ANCHOR_RE.match(text)
            if not match:
                continue
            question_no = int(match.group(1))
            anchors.append(
                QuestionAnchor(
                    question_no=question_no,
                    page_no=block.page_no,
                    column=block.column,
                    block_index=i,
                )
            )
        return anchors

9.7 segmenters/question_segmenter.py

from __future__ import annotations
from pdf_pipeline.segmenters.choice_parser import ChoiceParser
from pdf_pipeline.segmenters.question_anchor_finder import QuestionAnchor
from pdf_pipeline.types import Question, TextBlock
class QuestionSegmenter:
    def __init__(self) -> None:
        self.choice_parser = ChoiceParser()
    def segment(self, blocks: list[TextBlock], anchors: list[QuestionAnchor]) -> list[Question]:
        questions: list[Question] = []
        for idx, anchor in enumerate(anchors):
            start = anchor.block_index
            end = anchors[idx + 1].block_index if idx + 1 < len(anchors) else len(blocks)
            q_blocks = blocks[start:end]
            raw_text = "\n".join(block.text for block in q_blocks)
            stem, choices = self.choice_parser.parse(raw_text)
            questions.append(
                Question(
                    question_no=anchor.question_no,
                    subject=None,
                    stem=stem,
                    choices=choices,
                    raw_text=raw_text,
                    pages=sorted({b.page_no for b in q_blocks}),
                    columns=list(dict.fromkeys([b.column for b in q_blocks])),
                )
            )
        return questions

9.8 segmenters/choice_parser.py

from __future__ import annotations
import re
from pdf_pipeline.types import Choice
CHOICE_RE = re.compile(r"(①|②|③|④|⑤)")
class ChoiceParser:
    def parse(self, raw_text: str) -> tuple[str, list[Choice]]:
        parts = CHOICE_RE.split(raw_text)
        if len(parts) < 3:
            return raw_text.strip(), []
        stem = parts[0].strip()
        choices: list[Choice] = []
        i = 1
        while i + 1 < len(parts):
            label = parts[i].strip()
            text = parts[i + 1].strip()
            choices.append(Choice(label=label, text=text))
            i += 2
        return stem, choices

9.9 extractors/image_extractor.py

from __future__ import annotations
from pathlib import Path
import fitz
from pdf_pipeline.types import Asset, BBox, PageAnalysis
class ImageExtractor:
    def __init__(self, output_dir: str = "artifacts/assets") -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
    def extract(self, pdf_path: str, page_analyses: list[PageAnalysis]) -> list[Asset]:
        doc = fitz.open(pdf_path)
        assets: list[Asset] = []
        page_analysis_map = {p.page_no: p for p in page_analyses}
        for page_no, page_analysis in page_analysis_map.items():
            page = doc[page_no - 1]
            page_dict = page.get_text("dict")
            page_width = page.rect.width
            center = page_width / 2
            image_idx = 0
            for block in page_dict.get("blocks", []):
                if block.get("type") != 1:
                    continue
                x0, y0, x1, y1 = block["bbox"]
                bbox = BBox(x0, y0, x1, y1)
                if self._is_filtered_asset(bbox, page_analysis):
                    continue
                column = "full"
                if page_analysis.is_two_column:
                    block_center = (x0 + x1) / 2
                    column = "left" if block_center < center else "right"
                image_idx += 1
                path = self.output_dir / f"page_{page_no:03d}_img_{image_idx:02d}.png"
                assets.append(
                    Asset(
                        page_no=page_no,
                        bbox=bbox,
                        asset_type="image",
                        path=str(path),
                        column=column,
                    )
                )
        return assets
    def _is_filtered_asset(self, bbox: BBox, page_analysis: PageAnalysis) -> bool:
        if bbox.area < 400:
            return True
        if page_analysis.header_band and bbox.y1 <= page_analysis.header_band.y1:
            return True
        if page_analysis.footer_band and bbox.y0 >= page_analysis.footer_band.y0:
            return True
        return False

9.10 segmenters/asset_mapper.py

from __future__ import annotations
from pdf_pipeline.types import Asset, Question
class AssetMapper:
    def map(self, questions: list[Question], assets: list[Asset]) -> list[Question]:
        for asset in assets:
            candidate = self._find_best_question(asset, questions)
            if candidate is not None:
                candidate.assets.append(asset)
        return questions
    def _find_best_question(self, asset: Asset, questions: list[Question]) -> Question | None:
        candidates: list[Question] = []
        for q in questions:
            if asset.page_no not in q.pages:
                continue
            if q.columns and asset.column not in q.columns and "full" not in q.columns:
                continue
            candidates.append(q)
        if not candidates:
            return None
        return sorted(candidates, key=lambda q: q.question_no)[-1]

9.11 extractors/answer_extractor.py

from __future__ import annotations
import re
import fitz
from pdf_pipeline.types import PageAnalysis
ANSWER_RE = re.compile(r"(\d{1,3})\.\s*([①②③④⑤])")
class AnswerExtractor:
    def extract(self, pdf_path: str, page_analyses: list[PageAnalysis]) -> dict[int, str]:
        doc = fitz.open(pdf_path)
        answers: dict[int, str] = {}
        for page_analysis in page_analyses:
            page = doc[page_analysis.page_no - 1]
            text = page.get_text("text")
            if "정답 및 해설" not in text and "정답" not in text:
                continue
            for q_no, answer in ANSWER_RE.findall(text):
                answers[int(q_no)] = answer
        return answers

9.12 validators/confidence_scorer.py

from __future__ import annotations
from pdf_pipeline.types import Question
class ConfidenceScorer:
    def score(self, questions: list[Question]) -> list[Question]:
        for q in questions:
            score = 1.0
            if not q.stem:
                score -= 0.4
            if len(q.choices) not in (0, 4, 5):
                score -= 0.2
            if q.answer is None:
                score -= 0.1
            if len(q.raw_text) < 20:
                score -= 0.2
            q.confidence = max(0.0, min(1.0, score))
        return questions

9.13 validators/exam_validator.py

from __future__ import annotations
class ExamValidator:
    def validate(self, questions, answers) -> None:
        question_numbers = [q.question_no for q in questions]
        if not question_numbers:
            raise ValueError("질문(anchor) 추출 결과가 비어 있습니다.")
        if len(set(question_numbers)) != len(question_numbers):
            raise ValueError("중복된 문제 번호가 존재합니다.")
        missing_answers = [q.question_no for q in questions if q.question_no not in answers]
        if missing_answers:
            print(f"[WARN] answer missing: {missing_answers[:10]}")

⸻

10. 디버그/관측성 요구사항

구현 Agent는 반드시 중간 산출물을 저장해야 한다.

저장 권장 항목

* 페이지별 분석 결과 JSON
* 컬럼 분할 디버그 이미지
* 헤더/푸터 제거 전후 텍스트 비교
* anchor 위치 목록
* 문항별 raw_text 덤프
* asset bbox overlay 이미지
* 최종 questions.json

이유

시험지 파싱은 규칙이 미세하게 틀어지기 쉽기 때문에,
중간 결과를 보지 않으면 디버깅 비용이 급증한다.

⸻

11. 테스트 전략

11.1 단위 테스트

대상

* 문제번호 정규식
* 보기 파서
* 정답 파서
* 헤더/푸터 필터
* 컬럼 분할 판별

예시

* 1. 문제 본문 ... → anchor 검출
* ① A ② B ③ C ④ D → choices 4개 검출
* 1.① 2.③ → answer map 생성

11.2 통합 테스트

목표

샘플 PDF 1개 이상에 대해 다음을 검증한다.

* 문제 수가 기대치와 대략 일치
* 문제 번호가 단조 증가
* 답안 수가 충분
* 특정 문제(예: 8번)가 이미지/본문 매핑을 유지

11.3 회귀 테스트

다양한 연도/회차 PDF를 fixture로 보관한다.

권장 분류:

* 텍스트층 + 2단 시험지
* 텍스트층 + 1단 해설지
* 이미지 우세 PDF
* 표/그림이 많은 PDF

⸻

12. 구현 우선순위

Phase 1

* PDF 진단기
* 헤더/푸터 제거
* 2단 판별
* 문제번호 anchor 추출
* 문항 분리
* 정답 페이지 파싱

Phase 2

* 이미지 추출 및 문항 귀속
* confidence scoring
* 디버그 아티팩트 저장

Phase 3

* OCR fallback
* LLM fallback
* subject/과목 자동 인식
* 해설 텍스트 정교화

⸻

13. 구현 시 주의사항

1. 문항 분리는 텍스트 순차 추출이 아니라 anchor 기반이어야 한다.
2. 2단 판별 실패가 전체 파이프라인 품질을 가장 크게 떨어뜨린다.
3. 이미지 추출 자체보다 문항 귀속이 더 중요하다.
4. LLM은 주 경로가 아니라 fallback 으로 제한해야 한다.
5. 정답 페이지는 본문과 다른 파서로 처리해야 한다.
6. 첫 페이지와 마지막 페이지는 일반 본문 페이지와 동일 규칙으로 다루면 안 된다.

⸻

14. Agent 작업 지시 초안

다음 순서로 작업한다.

1. 저장소의 기존 PDF 파싱 진입점을 찾는다.
2. PDF 전처리 레이어를 추가할 수 있는 위치를 식별한다.
3. 위 문서의 analyzers / extractors / segmenters / validators 구조를 기준으로 모듈을 추가한다.
4. 최소 기능부터 구현한다.
    * 2단 판별
    * 헤더/푸터 제거
    * 문제번호 anchor 분리
    * 정답 파싱
5. 샘플 PDF 1개로 중간 결과를 디버그 파일로 저장한다.
6. 문항 수 / 정답 수 / 누락 문항을 점검한다.
7. 이미지 귀속은 2차 작업으로 붙인다.
8. 실패 문항만 수집하여 fallback 대상으로 분류한다.

⸻

15. 최종 판단

이 문제는 OCR 성능 부족보다 시험지 레이아웃 복원 부족에 가깝다.
따라서 가장 먼저 투자해야 하는 것은 다음이다.

* PDF 구조 진단
* 2단 분할
* 문제번호 기반 세그멘테이션
* 정답/이미지의 문항 매핑

즉, opendataloader 자체를 계속 튜닝하는 것보다,
앞단에 시험지 전용 전처리 파이프라인을 추가하는 방식이 더 안정적이고 비용 대비 효과도 좋다.

원하시면 다음 답변에서 이걸 바로 이어서 **“Agent에게 붙여넣을 작업 프롬프트”** 형태로도 바꿔드리겠습니다.