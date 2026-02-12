import importlib.util
import json
import sys
from pathlib import Path


def load_module():
    module_name = "extract6_shared_module"
    module_path = Path(__file__).resolve().parents[1] / "6_extract_all_text_and_save_latex_split_images.py"
    spec = importlib.util.spec_from_file_location(module_name, str(module_path))
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_extract_shared_passages_detects_marker_in_choices_and_re_splits_text(tmp_path):
    module6 = load_module()
    module5 = module6.load_module_5()

    q19_p1 = tmp_path / "question_019_problem_part_01.png"
    q19_p2 = tmp_path / "question_019_problem_part_02.png"
    q19_p1.write_bytes(b"p1")
    q19_p2.write_bytes(b"p2")

    question_images = [
        module5.QuestionImageSet(
            index=19,
            qno=19,
            problem_image_paths=[str(q19_p1), str(q19_p2)],
            choices_image_paths=[],
        ),
        module5.QuestionImageSet(
            index=20,
            qno=20,
            problem_image_paths=[],
            choices_image_paths=[],
        ),
        module5.QuestionImageSet(
            index=21,
            qno=21,
            problem_image_paths=[],
            choices_image_paths=[],
        ),
    ]
    question_texts = [
        module5.QuestionTextSet(
            index=19,
            qno=19,
            question_text="19. (가)~(다) 순서로 옳은 것은?",
            choices_text=(
                "① A\n② B\n"
                "※ [20 ~ 21] 다음 글을 읽고 물음에 답하시오.\n"
                "공통 지문 본문"
            ),
        ),
        module5.QuestionTextSet(index=20, qno=20, question_text="20. 문제", choices_text="① A"),
        module5.QuestionTextSet(index=21, qno=21, question_text="21. 문제", choices_text="① B"),
    ]

    new_images, new_texts, shared_passages, shared_map = module6.extract_shared_passages(
        module5=module5,
        question_images=question_images,
        question_texts=question_texts,
        image_dir=tmp_path,
    )

    assert len(shared_passages) == 1
    shared = shared_passages[0]
    assert shared.start_qno == 20
    assert shared.end_qno == 21
    assert "[20 ~ 21]" in shared.text
    assert "공통 지문 본문" in shared.text
    assert len(shared.image_paths) == 1
    assert Path(shared.image_paths[0]).name == "shared_passage_020_021_part_01.png"
    assert Path(shared.image_paths[0]).read_bytes() == b"p2"

    assert new_images[0].problem_image_paths == [str(q19_p1)]
    assert "[20 ~ 21]" not in new_texts[0].question_text
    assert "[20 ~ 21]" not in new_texts[0].choices_text
    assert "공통 지문 본문" not in new_texts[0].choices_text
    assert "19. (가)~(다) 순서로 옳은 것은?" in new_texts[0].question_text
    assert "① A" in new_texts[0].choices_text
    assert shared_map[20] == "shared_passage_020_021"
    assert shared_map[21] == "shared_passage_020_021"


def test_extract_shared_passages_fallbacks_to_last_choices_image_when_problem_single(tmp_path):
    module6 = load_module()
    module5 = module6.load_module_5()

    q19_p1 = tmp_path / "question_019_problem_part_01.png"
    q19_c1 = tmp_path / "question_019_choices_part_01.png"
    q19_p1.write_bytes(b"p1")
    q19_c1.write_bytes(b"c1")

    question_images = [
        module5.QuestionImageSet(
            index=19,
            qno=19,
            problem_image_paths=[str(q19_p1)],
            choices_image_paths=[str(q19_c1)],
        ),
        module5.QuestionImageSet(
            index=20,
            qno=20,
            problem_image_paths=[],
            choices_image_paths=[],
        ),
        module5.QuestionImageSet(
            index=21,
            qno=21,
            problem_image_paths=[],
            choices_image_paths=[],
        ),
    ]
    question_texts = [
        module5.QuestionTextSet(
            index=19,
            qno=19,
            question_text="19. 문제",
            choices_text="[20-21] 다음 글을 읽고 물음에 답하시오.\n공통 지문",
        ),
        module5.QuestionTextSet(index=20, qno=20, question_text="20. 문제", choices_text=""),
        module5.QuestionTextSet(index=21, qno=21, question_text="21. 문제", choices_text=""),
    ]

    new_images, _new_texts, shared_passages, _shared_map = module6.extract_shared_passages(
        module5=module5,
        question_images=question_images,
        question_texts=question_texts,
        image_dir=tmp_path,
    )

    shared = shared_passages[0]
    assert Path(shared.image_paths[0]).read_bytes() == b"c1"
    assert new_images[0].problem_image_paths == [str(q19_p1)]
    assert new_images[0].choices_image_paths == []


def test_save_split_texts_writes_shared_passage_and_map(tmp_path):
    module6 = load_module()
    module5 = module6.load_module_5()
    out_dir = tmp_path / "question_texts"
    out_dir.mkdir(parents=True, exist_ok=True)

    question_texts = [
        module5.QuestionTextSet(index=20, qno=20, question_text="20. 문제", choices_text="① A"),
        module5.QuestionTextSet(index=21, qno=21, question_text="21. 문제", choices_text="① B"),
    ]
    shared_passages = [
        module6.SharedPassageSet(
            passage_id="shared_passage_020_021",
            start_qno=20,
            end_qno=21,
            text="[20~21] 공통 지문",
            image_paths=[],
        )
    ]
    shared_map = {20: "shared_passage_020_021", 21: "shared_passage_020_021"}

    module6.save_split_texts(
        module5=module5,
        out_dir=out_dir,
        question_texts=question_texts,
        shared_passages=shared_passages,
        shared_map=shared_map,
    )

    shared_text_path = out_dir / "shared_passage_020_021.txt"
    mapping_path = out_dir / "question_passage_map.json"
    assert shared_text_path.exists()
    assert mapping_path.exists()
    assert "[20~21] 공통 지문" in shared_text_path.read_text(encoding="utf-8")
    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    assert mapping["20"]["shared_passage"] == "shared_passage_020_021.txt"
    assert mapping["21"]["shared_passage"] == "shared_passage_020_021.txt"


def test_build_latex_document_places_shared_passage_above_target_question():
    module6 = load_module()
    module5 = module6.load_module_5()
    question_images = [
        module5.QuestionImageSet(
            index=19,
            qno=19,
            problem_image_paths=["questions/question_019_problem_part_01.png"],
            choices_image_paths=["questions/question_019_choices_part_01.png"],
        ),
        module5.QuestionImageSet(
            index=20,
            qno=20,
            problem_image_paths=["questions/question_020_problem_part_01.png"],
            choices_image_paths=["questions/question_020_choices_part_01.png"],
        ),
    ]
    shared_passages = [
        module6.SharedPassageSet(
            passage_id="shared_passage_020_021",
            start_qno=20,
            end_qno=21,
            text="[20~21] 공통 지문",
            image_paths=["questions/shared_passage_020_021_part_01.png"],
        )
    ]

    tex = module6.build_latex_document(
        module5=module5,
        pdf_name="level4.pdf",
        question_images=question_images,
        shared_passages=shared_passages,
        shared_map={20: "shared_passage_020_021", 21: "shared_passage_020_021"},
    )

    assert r"\subsection*{Shared Passage (No. 20-21)}" in tex
    assert "shared_passage_020_021_part_01.png" in tex
    assert tex.find(r"\subsection*{Shared Passage (No. 20-21)}") < tex.find(
        r"\section*{Question 20 (No. 20)}"
    )
