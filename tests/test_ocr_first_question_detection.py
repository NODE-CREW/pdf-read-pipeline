import pipelines.base as base


def test_enhance_question_texts_with_ocr_splits_multiple_questions_from_single_ocr(monkeypatch):
    module5 = base.load_module_5()

    images = [
        module5.QuestionImageSet(
            index=1,
            qno=1,
            problem_image_paths=["/tmp/q1_problem.png"],
            choices_image_paths=[],
        )
    ]
    texts = [
        module5.QuestionTextSet(index=1, qno=1, question_text="", choices_text="")
    ]

    ocr_text = "\n".join(
        [
            "1. 첫 번째 문제",
            "문제 본문",
            "@ 보기A",
            "@ 보기B",
            "@ 보기C",
            "@ 보기D",
            "2. 두 번째 문제",
            "문제 본문",
            "@ 보기A",
            "@ 보기B",
            "@ 보기C",
            "@ 보기D",
        ]
    )
    monkeypatch.setattr(base, "ocr_text_from_image_paths", lambda *_args, **_kwargs: ocr_text)

    out = base.enhance_question_texts_with_ocr(
        module5=module5,
        question_images=images,
        question_texts=texts,
        min_chars=30,
        ocr_lang="kor+eng",
    )

    assert len(out) == 2
    assert out[0].index == 1
    assert out[0].qno == 1
    assert out[1].index == 2
    assert out[1].qno == 2
    assert "첫 번째 문제" in out[0].question_text
    assert "두 번째 문제" in out[1].question_text


def test_enhance_question_texts_with_ocr_uses_next_free_index_for_extra_questions(monkeypatch):
    module5 = base.load_module_5()

    images = [
        module5.QuestionImageSet(
            index=1,
            qno=1,
            problem_image_paths=["/tmp/q1_problem.png"],
            choices_image_paths=[],
        ),
        module5.QuestionImageSet(
            index=2,
            qno=99,
            problem_image_paths=["/tmp/q2_problem.png"],
            choices_image_paths=[],
        ),
    ]
    texts = [
        module5.QuestionTextSet(index=1, qno=1, question_text="", choices_text=""),
        module5.QuestionTextSet(index=2, qno=99, question_text="기존 텍스트", choices_text=""),
    ]

    ocr_text = "\n".join(
        [
            "1. 첫 번째 문제",
            "본문",
            "@ 보기A",
            "@ 보기B",
            "@ 보기C",
            "@ 보기D",
            "2. 두 번째 문제",
            "본문",
            "@ 보기A",
            "@ 보기B",
            "@ 보기C",
            "@ 보기D",
        ]
    )
    monkeypatch.setattr(base, "ocr_text_from_image_paths", lambda *_args, **_kwargs: ocr_text)

    out = base.enhance_question_texts_with_ocr(
        module5=module5,
        question_images=images,
        question_texts=texts,
        min_chars=30,
        ocr_lang="kor+eng",
    )

    assert [item.index for item in out] == [1, 2, 3]
    assert [item.qno for item in out] == [1, 99, 2]


def test_enhance_question_texts_with_ocr_normalizes_nearly_consecutive_qno_sequence(monkeypatch):
    module5 = base.load_module_5()

    images = [
        module5.QuestionImageSet(
            index=1,
            qno=1,
            problem_image_paths=["/tmp/q1_problem.png"],
            choices_image_paths=[],
        )
    ]
    texts = [
        module5.QuestionTextSet(index=1, qno=1, question_text="", choices_text="")
    ]

    lines = []
    for qno in [1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 12, 13]:
        lines.extend(
            [
                f"{qno}. 문항",
                "본문",
                "@ 보기A",
                "@ 보기B",
                "@ 보기C",
                "@ 보기D",
            ]
        )
    monkeypatch.setattr(base, "ocr_text_from_image_paths", lambda *_args, **_kwargs: "\n".join(lines))

    out = base.enhance_question_texts_with_ocr(
        module5=module5,
        question_images=images,
        question_texts=texts,
        min_chars=30,
        ocr_lang="kor+eng",
    )

    assert [item.qno for item in out] == list(range(1, 13))
