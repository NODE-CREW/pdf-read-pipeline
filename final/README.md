# Final PDF Parser

PDF 시험지에서 문제, 선지, 이미지, 해설 보강 정보를 추출해 최종 JSON으로 만드는 파이프라인이다.

## 목적

- 최종 실행 경로를 `final/` 안에 둔다.
- 시나공 PDF 파서와 일반 PDF 구조 파서를 함께 지원한다.
- 두 파서의 서로 다른 출력 형태를 하나의 최종 JSON 스키마로 정규화한다.
- 이미지 caption, 힌트 해설, 선지 해설, 정답 추론이 필요한 경우 OpenAI-compatible ngrok endpoint로 보강한다.

## 폴더 구조

```text
final/
  README.md
  plan.md
  tasklist.md
  parse_pdf.py
  sinagong_pdf_parser.py
  normalizer.py
  schema.py
  text_refiner.py
  ai_enricher.py
  image_captioner.py
  normal_pdf_parser/
    extract_pdf.py
    generate_answer.py
    batch_generate_answer.py
    generate_concept.py
    batch_generate_concept.py
    extract_questions.py
```

## 파서 기준

- `sinagong`: `sinagong_pdf_parser.py`를 사용한다.
- `normal`: 일반 PDF 구조 파서인 `normal_pdf_parser/`를 사용한다.
- `--parser`를 생략하면 실행 중 `input()`으로 `sinagong` 또는 `normal`을 다시 묻는다.

## 실행 예시

```bash
python final/parse_pdf.py \
  --pdf ./data/test-1.pdf \
  --output-dir ./final/output/test-1 \
  --parser sinagong \
  --ai-base-url https://varying-pushcart-ladle.ngrok-free.dev/v1 \
  --model mlx-community/gemma-4-26b-a4b-it-4bit
```

AI 보강 없이 파서 결과만 확인하려면 `--ai-base-url`을 생략한다.

```bash
python final/parse_pdf.py \
  --pdf ./data/test-1.pdf \
  --output-dir ./final/output/test-1 \
  --parser sinagong
```

AI endpoint는 사용하되 문제/선지 텍스트 정제를 건너뛰려면 `--skip-text-refine`을 추가한다.

AI 요청 timeout은 60초, 반복 실패 시 남은 AI 작업을 건너뛰는 기준은 3회로 코드에 설정되어 있으며 CLI 입력으로 받지 않는다. OpenAI SDK 내부 재시도는 끄고 파이프라인의 재시도/실패 정책만 적용한다.

## 출력 구조

```text
final/output/<pdf-name>/
  questions_final.json
  images/
    image001.png
    image002.png
```

`questions_final.json`은 아래 형태를 따른다.

```json
{
  "source_pdf": "test-1.pdf",
  "questions": [
    {
      "content": "다음 중 옳은 것은? [image001]",
      "question_source": "test-1.pdf 1번 문제",
      "images": [
        {
          "image_id": "image001",
          "image_name": "image001.png",
          "image_caption": "그림 설명"
        }
      ],
      "hint_explanation": "문제 풀이 힌트 또는 해설",
      "options": [
        {
          "order": 1,
          "is_correct": true,
          "content": "선지 내용",
          "images": [],
          "option_explanation": "선지 해설"
        }
      ]
    }
  ],
  "metadata": {
    "total_questions": 1,
    "total_images": 1,
    "requires_answer_review": false
  }
}
```

## AI Endpoint 설정

OpenAI-compatible ngrok endpoint를 사용한다.

```python
from openai import OpenAI

client = OpenAI(
    base_url="https://varying-pushcart-ladle.ngrok-free.dev/v1",
    api_key="any-string-ok",
)
```

AI는 세 단계로 사용한다.

1. `text_refiner.py`: 문제 본문과 선지 본문의 OCR/파싱 오타, 띄어쓰기, 붙은 단어를 정제한다.
2. `ai_enricher.py`: 해설, 선지 해설, 정답 추론을 보강한다.
3. `image_captioner.py`: 실제 이미지와 문제/선지 맥락을 함께 보내 `image_caption`을 생성한다.

`text_refiner.py`는 다음 필드만 수정한다.

- `content`
- `options[].content`

프롬프트는 특정 오류 예시가 아니라 PDF 파싱 손상 복원 원칙을 전달한다. 글자 순서는 대체로 보존되지만 단어 경계, 띄어쓰기, 구두점 위치, 목록 구분자가 깨질 수 있다는 전제로 원문 시험지에 가까운 문장을 복원하도록 요청한다.

LLM은 `corrections`와 `confidence`도 함께 반환한다. 실제 최종 문제 객체에는 `content`와 `options[].content`만 반영하고, 수정 이력과 신뢰도는 `metadata.text_refinement.refined_questions`에 남긴다. `confidence`가 `low`이거나 artifact detector가 여전히 문제를 찾으면 `metadata.text_refinement.unresolved_artifacts`에 남겨 검수 대상으로 표시한다.

정제 전후 텍스트가 실제로 달라진 경우에는 실행 중 stderr에 로그를 출력한다.

```text
[text-refine changed] test-1.pdf 7번 문제 / content
- before: ...
- after: ...
```

`ai_enricher.py`는 다음 값 보강에 사용한다.

- `hint_explanation`
- `option_explanation`
- 정답표나 파서 결과에 정답이 없을 때 `is_correct`

`image_captioner.py`는 다음 값 보강에 사용한다.

- `image_caption`
- 이미지 내부 텍스트, 도형, 표, 관계, 배치 설명
- 문제 이미지의 경우 문제 본문과 전체 선지 텍스트를 맥락으로 함께 전달
- 선지 이미지의 경우 문제 본문, 전체 선지 텍스트, 해당 선지 텍스트를 맥락으로 함께 전달

문제 번호, 기본 문제 본문, 기본 선지 텍스트, 이미지 파일명, 이미지 ID, crop 생성은 파서와 로컬 로직으로 처리한다.

AI endpoint가 죽어 있거나 ngrok upstream이 연결되지 않으면 전체 변환은 중단하지 않는다. 파서 기반 `questions_final.json`을 저장하고, 실패 정보는 `metadata.text_refinement`, `metadata.ai_enrichment`, `metadata.image_captioning`에 기록한다. JSON 파싱 실패나 timeout처럼 같은 원인으로 반복될 가능성이 높은 실패가 3회에 도달하면 남은 AI 작업은 건너뛴다. timeout은 `metadata.text_refinement.timeout_questions`에 별도로 기록한다.

## 검수 필요 조건

다음 경우 `metadata.requires_answer_review`가 `true`가 될 수 있다.

- 정답표가 없고 AI도 정답을 확정하지 못한 경우
- 선택지는 있으나 `is_correct: true`인 선지가 없는 경우
- 이미지 OCR 또는 caption 생성이 실패한 경우
- 텍스트 정제가 실패한 경우
- 파서가 문제/선지 경계를 불완전하게 추정한 경우

## 한계

- 스캔본 PDF는 OCR 품질에 따라 결과가 달라진다.
- 표, 코드, 수식, 복잡한 도형은 crop은 가능해도 의미 해석은 AI 보강 품질에 의존한다.
- `sinagong` 파서는 `data/test-1.pdf`와 유사한 시나공 형식에 최적화되어 있다.
- `normal` 파서는 opendataloader 기반 JSON 생성 또는 기존 일반 PDF 파이프라인 의존성이 필요할 수 있다.
