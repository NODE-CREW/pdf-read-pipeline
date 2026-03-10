from pathlib import Path

import pipelines.base as base


def test_split_images_for_ocr_synthetic_questions_creates_per_question_images(tmp_path):
    pil_image = __import__("PIL.Image", fromlist=["Image"])

    image_path = tmp_path / "page_001.png"
    pil_image.new("RGB", (100, 400), color=(255, 255, 255)).save(image_path)

    module5 = base.load_module_5()
    question_images = [
        module5.QuestionImageSet(
            index=1,
            qno=1,
            problem_image_paths=[str(image_path)],
            choices_image_paths=[],
        )
    ]
    question_texts = [
        module5.QuestionTextSet(index=1, qno=1, question_text="q1", choices_text=""),
        module5.QuestionTextSet(index=2, qno=2, question_text="q2", choices_text=""),
        module5.QuestionTextSet(index=3, qno=3, question_text="q3", choices_text=""),
    ]

    out = base.expand_question_images_for_ocr_synthetic_questions(
        module5=module5,
        question_images=question_images,
        question_texts=question_texts,
    )

    assert [item.index for item in out] == [1, 2, 3]
    for item in out:
        assert len(item.problem_image_paths) == 1
        assert Path(item.problem_image_paths[0]).exists()
        assert item.choices_image_paths == []
