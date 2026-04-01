import importlib.util
import sys
from pathlib import Path

import pytest


def load_module():
    module_name = "concat_text_files"
    module_path = Path(__file__).resolve().parents[1] / "concat_text_files.py"
    spec = importlib.util.spec_from_file_location(module_name, str(module_path))
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_collect_text_files_sorts_by_filename_and_ignores_output_file(tmp_path):
    module = load_module()
    input_dir = tmp_path / "texts"
    input_dir.mkdir()
    (input_dir / "b.txt").write_text("B", encoding="utf-8")
    (input_dir / "a.txt").write_text("A", encoding="utf-8")
    (input_dir / "merged.txt").write_text("OLD", encoding="utf-8")
    (input_dir / "notes.md").write_text("skip", encoding="utf-8")

    text_files = module.collect_text_files(input_dir=input_dir, output_path=input_dir / "merged.txt")

    assert [path.name for path in text_files] == ["a.txt", "b.txt"]


def test_concat_text_contents_inserts_newline_only_when_needed(tmp_path):
    module = load_module()
    first = tmp_path / "a.txt"
    second = tmp_path / "b.txt"
    first.write_text("alpha", encoding="utf-8")
    second.write_text("beta\n", encoding="utf-8")

    merged = module.concat_text_contents([first, second])

    assert merged == "alpha\nbeta\n"


def test_run_raises_when_directory_has_no_text_files(tmp_path):
    module = load_module()
    input_dir = tmp_path / "texts"
    input_dir.mkdir()
    (input_dir / "notes.md").write_text("skip", encoding="utf-8")

    with pytest.raises(ValueError, match="txt"):
        module.run(
            input_dir=input_dir,
            output_path=tmp_path / "merged.txt",
        )


def test_run_writes_merged_text_file(tmp_path):
    module = load_module()
    input_dir = tmp_path / "texts"
    input_dir.mkdir()
    (input_dir / "001.txt").write_text("first\n", encoding="utf-8")
    (input_dir / "002.txt").write_text("second", encoding="utf-8")
    output_path = tmp_path / "merged.txt"

    written_path = module.run(
        input_dir=input_dir,
        output_path=output_path,
    )

    assert written_path == output_path.resolve()
    assert output_path.read_text(encoding="utf-8") == "first\nsecond"
