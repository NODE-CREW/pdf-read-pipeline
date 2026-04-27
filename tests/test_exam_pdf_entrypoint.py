import importlib.util
import json
import sys
from pathlib import Path


def load_module(path: str, name: str):
    module_path = Path(__file__).resolve().parents[1] / path
    spec = importlib.util.spec_from_file_location(name, str(module_path))
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_main_writes_json_output(monkeypatch, tmp_path, capsys):
    module = load_module("11_run_exam_pdf_pipeline.py", "entry_11_exam_pdf")

    sample_pdf = tmp_path / "sample.pdf"
    sample_pdf.write_bytes(b"%PDF-1.4\n")
    sample_json = tmp_path / "sample.json"
    sample_json.write_text("{}", encoding="utf-8")

    class FakeOpenDataLoaderPDF:
        @staticmethod
        def convert(*, input_path, output_dir, format):
            assert input_path == [str(sample_pdf)]
            assert format == "json"
            Path(output_dir).mkdir(parents=True, exist_ok=True)
            (Path(output_dir) / "sample.json").write_text("{}", encoding="utf-8")

    monkeypatch.setitem(sys.modules, "opendataloader_pdf", FakeOpenDataLoaderPDF)

    monkeypatch.setattr(
        module,
        "parse_pdf_json",
        lambda json_path, pdf_path=None, out_dir=None, dpi=150: {
            "source": json_path.stem,
            "questions": [{"question_number": 1, "choices": [], "images": []}],
            "image_crops": [{"element_id": 1, "crop_path": "crops/crop_id0001_p1.png"}],
            "metadata": {"total_questions": 1, "pages": 1, "filtered_nodes": 0},
        },
    )

    output_dir = tmp_path / "out"
    rc = module.main([str(sample_pdf), "--output-dir", str(output_dir)])

    assert rc == 0
    output_path = output_dir / "sample_questions.json"
    assert output_path.exists()

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["metadata"]["total_questions"] == 1
    assert "[saved]" in capsys.readouterr().out


def test_build_output_path_uses_pdf_stem(tmp_path):
    module = load_module("11_run_exam_pdf_pipeline.py", "entry_11_exam_pdf_path")

    out_path = module.build_output_path(tmp_path / "foo.bar.pdf", tmp_path / "output")

    assert out_path == tmp_path / "output" / "foo.bar_questions.json"


def test_main_raises_when_opendataloader_missing(tmp_path):
    module = load_module("11_run_exam_pdf_pipeline.py", "entry_11_exam_pdf_missing")

    sample_pdf = tmp_path / "sample.pdf"
    sample_pdf.write_bytes(b"%PDF-1.4\n")

    import importlib

    original_import_module = importlib.import_module

    def fake_import_module(name, package=None):
        if name == "opendataloader_pdf":
            raise ImportError("missing opendataloader_pdf")
        return original_import_module(name, package)

    module.importlib.import_module = fake_import_module

    try:
        module.main([str(sample_pdf), "--output-dir", str(tmp_path / "out")])
    except ImportError as exc:
        assert "opendataloader-pdf" in str(exc)
    else:
        raise AssertionError("ImportError가 발생해야 합니다.")
