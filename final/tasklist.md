# Final PDF 파싱 파이프라인 작업 목록

## 1. 파일 구성

- [x] `final/` 폴더 생성
- [x] `new/test1_parser.py`를 `final/sinagong_pdf_parser.py`로 복사
- [x] `result/pdf_split_answer_concept_extract` 기반 파일을 `final/result_pdf_parser/`로 복사
- [x] `final/README.md` 작성
- [x] `final/plan.md` 작성
- [x] `final/tasklist.md` 작성

## 2. 테스트 작성

- [x] `sinagong_pdf_parser.py` import 테스트 추가
- [x] `result_pdf_parser` import 테스트 추가
- [x] 최종 스키마 생성 테스트 추가
- [x] 이미지 ID 전역 순번 테스트 추가
- [x] `[image001]` 토큰 삽입 테스트 추가
- [x] AI JSON 재시도 테스트 추가
- [x] `--parser auto` fallback 테스트 추가

## 3. 구현

- [x] `parse_pdf.py` CLI 구현
- [x] `normalizer.py` 구현 완료
- [x] `schema.py` 구현 완료
- [x] `text_refiner.py` 구현 완료
- [x] `ai_enricher.py` 구현 완료
- [x] 이름 변경으로 깨진 result parser 내부 참조 수정
- [x] `questions_final.json` 저장 구현
- [x] `images/` 복사 구현
- [x] AI 보강 옵션 구현
- [x] LLM 텍스트 정제 호출 구현
- [x] 범용 PDF 파싱 손상 복원 프롬프트 적용
- [x] 텍스트 정제 `corrections`/`confidence` metadata 기록 구현

## 4. 문서 보강

- [x] `final/README.md`에 목적 작성
- [x] `final/README.md`에 폴더 구조 작성
- [x] `final/README.md`에 실행 예시 작성
- [x] `final/README.md`에 AI endpoint 설정 작성
- [x] `final/README.md`에 LLM 텍스트 정제 단계 작성
- [x] `final/README.md`에 출력 JSON 구조 작성
- [x] `final/README.md`에 파서 선택 옵션 작성
- [x] `final/README.md`에 한계와 검수 필요 조건 작성
- [x] 루트 `README.md`에 `final/README.md` 링크와 간단 실행 예시 추가

## 5. 검증

- [x] `pytest tests/test_final_pipeline.py` 실행
- [x] 가능하면 `data/test-1.pdf` 통합 실행
- [x] 생성된 `questions_final.json` 구조 확인
- [x] 생성된 `images/` 파일명과 JSON 참조 일치 확인
