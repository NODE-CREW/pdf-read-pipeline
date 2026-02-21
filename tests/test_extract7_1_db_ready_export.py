import hashlib
import importlib.util
import json
import sys
from pathlib import Path


def load_module():
    module_name = "extract7_1_db_ready_module"
    module_path = (
        Path(__file__).resolve().parents[1] / "7_1_extract_all_text_and_save_latex_split_images.py"
    )
    spec = importlib.util.spec_from_file_location(module_name, str(module_path))
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _build_fixture(module7, module5):
    question_images = [
        module5.QuestionImageSet(
            index=1,
            qno=19,
            problem_image_paths=[
                "/tmp/output/level4/latex_pages/question_001_problem_part_01.png",
            ],
            choices_image_paths=[
                "/tmp/output/level4/latex_pages/question_001_choices_part_01.png",
            ],
        ),
        module5.QuestionImageSet(
            index=2,
            qno=None,
            problem_image_paths=[
                "/tmp/output/level4/latex_pages/question_002_problem_part_01.png",
            ],
            choices_image_paths=[],
        ),
    ]
    question_texts = [
        module5.QuestionTextSet(index=1, qno=19, question_text="문제 19", choices_text="① A"),
        module5.QuestionTextSet(index=2, qno=None, question_text="", choices_text=""),
    ]
    shared_passages = [
        module7.SharedPassageSet(
            passage_id="shared_passage_020_021",
            start_qno=20,
            end_qno=21,
            text="[20~21] 공통 지문",
            image_paths=[
                "/tmp/output/level4/latex_pages/shared_passage_020_021_part_01.png",
            ],
        )
    ]
    shared_map = {19: "shared_passage_020_021"}
    return question_images, question_texts, shared_passages, shared_map


def test_build_db_ready_records_includes_shared_fields_and_relative_paths():
    module7 = load_module()
    module5 = module7.load_module_5()
    question_images, question_texts, shared_passages, shared_map = _build_fixture(module7, module5)

    records = module7.build_db_ready_records(
        pdf_path="/tmp/input/level4.pdf",
        target_dir=Path("/tmp/output/level4"),
        question_images=question_images,
        question_texts=question_texts,
        shared_passages=shared_passages,
        shared_map=shared_map,
    )

    assert len(records) == 2
    first = records[0]
    second = records[1]

    assert first["schema_version"] == "v1"
    assert first["source_pdf_name"] == "level4.pdf"
    assert first["source_pdf_stem"] == "level4"
    assert first["shared_passage_id"] == "shared_passage_020_021"
    assert first["shared_passage_text"] == "[20~21] 공통 지문"
    assert first["shared_passage_image_paths"] == [
        "latex_pages/shared_passage_020_021_part_01.png"
    ]
    assert first["problem_image_paths"] == ["latex_pages/question_001_problem_part_01.png"]
    assert first["choices_image_paths"] == ["latex_pages/question_001_choices_part_01.png"]

    assert second["question_number"] is None
    assert second["shared_passage_id"] is None
    assert second["shared_passage_text"] is None
    assert second["shared_passage_image_paths"] == []
    assert ":na:" in second["record_id"]


def test_build_db_ready_records_record_id_is_stable_for_same_input():
    module7 = load_module()
    module5 = module7.load_module_5()
    question_images, question_texts, shared_passages, shared_map = _build_fixture(module7, module5)

    records_a = module7.build_db_ready_records(
        pdf_path="/tmp/input/level4.pdf",
        target_dir=Path("/tmp/output/level4"),
        question_images=question_images,
        question_texts=question_texts,
        shared_passages=shared_passages,
        shared_map=shared_map,
    )
    records_b = module7.build_db_ready_records(
        pdf_path="/tmp/input/level4.pdf",
        target_dir=Path("/tmp/output/level4"),
        question_images=question_images,
        question_texts=question_texts,
        shared_passages=shared_passages,
        shared_map=shared_map,
    )

    assert records_a[0]["record_id"] == records_b[0]["record_id"]
    assert records_a[1]["record_id"] == records_b[1]["record_id"]


def test_build_db_ready_records_content_hash_uses_normalized_text():
    module7 = load_module()
    module5 = module7.load_module_5()

    question_images = [
        module5.QuestionImageSet(index=1, qno=1, problem_image_paths=[], choices_image_paths=[])
    ]
    question_texts = [
        module5.QuestionTextSet(index=1, qno=1, question_text="A\n\nB", choices_text=" C\t\tD ")
    ]

    records = module7.build_db_ready_records(
        pdf_path="/tmp/input/sample.pdf",
        target_dir=Path("/tmp/output/sample"),
        question_images=question_images,
        question_texts=question_texts,
        shared_passages=[],
        shared_map={},
    )

    normalized = "A B C D"
    expected_hash = hashlib.sha1(normalized.encode("utf-8")).hexdigest()
    assert records[0]["content_hash"] == expected_hash


def test_save_db_ready_jsonl_writes_one_line_per_question(tmp_path):
    module7 = load_module()
    records = [
        {"question_index": 1, "record_id": "r1"},
        {"question_index": 2, "record_id": "r2"},
    ]

    out_path = module7.save_db_ready_jsonl(tmp_path, records)

    lines = out_path.read_text(encoding="utf-8").splitlines()
    assert out_path.name == "questions_db_ready.jsonl"
    assert len(lines) == 2
    assert json.loads(lines[0])["record_id"] == "r1"
    assert json.loads(lines[1])["record_id"] == "r2"


def test_save_split_texts_and_db_ready_jsonl_can_coexist(tmp_path):
    module7 = load_module()
    module5 = module7.load_module_5()
    out_dir = tmp_path / "question_texts"

    question_texts = [
        module5.QuestionTextSet(index=1, qno=1, question_text="문제", choices_text="① 보기")
    ]
    module7.save_split_texts(
        module5=module5,
        out_dir=out_dir,
        question_texts=question_texts,
        shared_passages=[],
        shared_map={},
    )

    records = [
        {
            "schema_version": "v1",
            "record_id": "sample:001:1:abc",
            "source_pdf_name": "sample.pdf",
            "source_pdf_stem": "sample",
            "question_index": 1,
            "question_number": 1,
            "question_text": "문제",
            "choices_text": "① 보기",
            "shared_passage_id": None,
            "shared_passage_text": None,
            "problem_image_paths": [],
            "choices_image_paths": [],
            "shared_passage_image_paths": [],
            "content_hash": "abc",
        }
    ]
    out_path = module7.save_db_ready_jsonl(out_dir, records)

    assert (out_dir / "question_001_problem.txt").exists()
    assert (out_dir / "question_001_choices.txt").exists()
    assert out_path.exists()
