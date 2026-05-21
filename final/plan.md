# Final PDF 파싱 파이프라인 구현 계획

## 목표

PDF를 입력받아 문제, 선지, 이미지, 정답 여부, 해설을 포함한 최종 JSON을 생성한다.

기존 파서는 삭제하거나 이동하지 않는다. `final/` 아래에 복사본을 두고, 역할이 명확한 이름으로 바꿔 새 파이프라인에서 사용한다.

## 파일 구성

```text
final/
  parse_pdf.py
  sinagong_pdf_parser.py
  normalizer.py
  schema.py
  text_refiner.py
  ai_enricher.py
  result_pdf_parser/
    extract_pdf.py
    generate_answer.py
    batch_generate_answer.py
    generate_concept.py
    batch_generate_concept.py
    extract_questions.py
```

## 기존 파일 매핑

| 원본 | final 복사본 |
| --- | --- |
| `new/test1_parser.py` | `final/sinagong_pdf_parser.py` |
| `result/pdf_split_answer_concept_extract/1_extract_all_text_and_save_latex_split_images.py` | `final/result_pdf_parser/extract_pdf.py` |
| `result/pdf_split_answer_concept_extract/2-1_generate_exam_answer_json_to_txt.py` | `final/result_pdf_parser/generate_answer.py` |
| `result/pdf_split_answer_concept_extract/2-2_batch_generate_exam_answer_json_to_txt.py` | `final/result_pdf_parser/batch_generate_answer.py` |
| `result/pdf_split_answer_concept_extract/3-1_generate_exam_single_concept_json_to_txt.py` | `final/result_pdf_parser/generate_concept.py` |
| `result/pdf_split_answer_concept_extract/3-2_batch_generate_exam_single_concept_json_to_txt.py` | `final/result_pdf_parser/batch_generate_concept.py` |
| `result/pdf_split_answer_concept_extract/1-1_extract_questions_from_json.py` | `final/result_pdf_parser/extract_questions.py` |

복사 후 동적 import나 실행 스크립트 내부에서 기존 숫자 파일명을 참조하는 부분은 새 파일명에 맞게 수정한다.

## 처리 흐름

1. `parse_pdf.py`가 PDF 경로, 출력 디렉토리, 파서 선택값을 받는다.
2. `--parser auto`이면 `sinagong` 파서를 먼저 실행한다.
3. `sinagong` 파서가 실패하면 `result` 파서로 fallback한다.
4. 파서 출력은 `normalizer.py`에서 공통 중간 구조로 변환한다.
5. `schema.py`가 이미지 ID를 전역 순번으로 부여하고 최종 JSON 구조를 만든다.
6. 이미지 파일은 `images/image001.png` 형식으로 복사한다.
7. 문제/선지 본문에는 이미지 참조 토큰 `[image001]`을 삽입한다.
8. `text_refiner.py`가 문제 본문과 선지 본문의 OCR/파싱 오타를 정제한다.
9. `ai_enricher.py`가 필요한 필드만 AI로 보강한다.
10. `questions_final.json`을 저장한다.

## 최종 스키마 규칙

- 최종 출력 루트는 `source_pdf`, `questions`, `metadata`를 가진다.
- 각 문제는 `content`, `question_source`, `images`, `hint_explanation`, `options`를 가진다.
- 각 선지는 `order`, `is_correct`, `content`, `images`, `option_explanation`을 가진다.
- 이미지 ID는 PDF 전체에서 중복 없이 `image001`부터 시작한다.
- 이미지 파일명은 이미지 ID와 동일한 이름을 사용한다. 예: `image001.png`
- 정답이 확정되지 않으면 `metadata.requires_answer_review`를 `true`로 둔다.

## AI 보강 범위

AI는 파서만으로 안정적으로 만들기 어려운 정보에 한정해서 사용한다.

텍스트 정제 단계는 `text_refiner.py`가 담당하며, 아래 필드만 수정한다.

- 문제 본문: `content`
- 선지 본문: `options[].content`

텍스트 정제 프롬프트는 특정 오류 예시가 아니라 PDF 파싱 손상 복원 원칙을 전달한다. LLM 응답의 `corrections`와 `confidence`는 최종 문제 객체에 넣지 않고 `metadata.text_refinement.refined_questions`에 기록한다. `confidence`가 낮거나 artifact가 남으면 검수 대상으로 남긴다.

이미지 토큰(`[image001]`)은 유지하고, 새 정보나 정답/해설은 만들지 않는다.

- 이미지 설명: `image_caption`
- 문제 해설 또는 힌트: `hint_explanation`
- 선지별 해설: `option_explanation`
- 정답 정보가 없을 때: `is_correct`
- 이미지 안 텍스트가 필요한 경우: OCR/내용 보강

AI를 쓰지 않고 결정할 값은 로컬 로직으로 처리한다.

- 문제 번호
- 문제 본문
- 선지 본문
- 이미지 crop 생성
- 이미지 ID
- 이미지 파일명
- 이미지의 문제/선지 소속 1차 매핑

## 검증 전략

UI 변경이 아니므로 테스트를 먼저 작성한다.

- `sinagong_pdf_parser.py` import 확인
- `result_pdf_parser` 하위 모듈 import 확인
- 최종 스키마 생성 확인
- 이미지 ID 전역 순번 확인
- `[image001]` 토큰 삽입 확인
- AI 응답 JSON 검증 및 재시도 확인
- LLM 텍스트 정제 성공/실패 동작 확인
- `--parser auto` fallback 확인
- `data/test-1.pdf`가 있으면 통합 실행으로 `questions_final.json`과 `images/` 생성을 확인

## 문서 반영

새로운 실행 흐름을 추가했으므로 루트 `README.md`에 간단한 실행 예시와 `final/README.md` 링크를 추가한다.
