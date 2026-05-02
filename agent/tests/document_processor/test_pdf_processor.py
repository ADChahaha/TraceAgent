from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest


class FakeDocument:
    def __init__(self, html: object = "<html><body>测试正文</body></html>") -> None:
        self.html = html
        self.export_kwargs = None

    def export_to_html(self, **kwargs):
        self.export_kwargs = kwargs
        return self.html


class FakeDocumentConverter:
    instances = []

    def __init__(self, *args, **kwargs) -> None:
        self.calls = []
        self.init_args = args
        self.init_kwargs = kwargs
        self.__class__.instances.append(self)

    def convert(self, stream):
        self.calls.append(stream)
        return SimpleNamespace(document=FakeDocument())


def test_convert_to_docling_document_wraps_pdf_bytes_and_filename(monkeypatch):
    from service.document_processor import docling_converter as processor_module

    FakeDocumentConverter.instances.clear()
    monkeypatch.setattr(
        processor_module,
        "DocumentConverter",
        FakeDocumentConverter,
    )

    document = processor_module.convert_to_docling_document(
        b"%PDF-1.4",
        "sample.pdf",
    )

    converter = FakeDocumentConverter.instances[0]
    converted_stream = converter.calls[0]

    assert isinstance(document, FakeDocument)
    assert converted_stream.name == "sample.pdf"
    assert converted_stream.stream.read() == b"%PDF-1.4"


def test_export_html_returns_docling_html():
    from service.document_processor import docling_converter as processor_module

    document = FakeDocument("<main>正文</main>")

    assert processor_module.export_html(document) == "<main>正文</main>"
    assert document.export_kwargs["include_annotations"] is False
    assert document.export_kwargs["labels"] == processor_module.semantic_docling_labels()


def test_export_html_rejects_non_string_docling_output():
    from service.document_processor import docling_converter as processor_module

    with pytest.raises(TypeError, match="export_to_html"):
        processor_module.export_html(FakeDocument(html=None))


def test_build_document_converter_enables_table_structure(monkeypatch):
    from service.document_processor import docling_converter as processor_module

    FakeDocumentConverter.instances.clear()
    monkeypatch.setattr(
        processor_module,
        "DocumentConverter",
        FakeDocumentConverter,
    )

    processor_module.build_document_converter()

    converter = FakeDocumentConverter.instances[0]
    format_options = converter.init_kwargs["format_options"]
    pdf_option = format_options[processor_module.InputFormat.PDF]

    assert pdf_option.pipeline_options.do_table_structure is True


def test_build_document_converter_uses_explicit_rapidocr(monkeypatch):
    from service.document_processor import docling_converter as processor_module

    FakeDocumentConverter.instances.clear()
    monkeypatch.setattr(
        processor_module,
        "DocumentConverter",
        FakeDocumentConverter,
    )

    processor_module.build_document_converter()

    converter = FakeDocumentConverter.instances[0]
    format_options = converter.init_kwargs["format_options"]
    pdf_option = format_options[processor_module.InputFormat.PDF]
    ocr_options = pdf_option.pipeline_options.ocr_options
    module_dir = Path(processor_module.__file__).resolve().parent

    assert type(ocr_options).__name__ == "RapidOcrOptions"
    assert ocr_options.backend == "onnxruntime"
    assert ocr_options.lang == ["chinese", "english"]
    assert Path(ocr_options.rapidocr_params["Global.model_root_dir"]) == (
        module_dir / "models" / "rapidocr"
    )


def test_build_document_converter_accepts_pdf_runtime_env_overrides(monkeypatch):
    from service.document_processor import docling_converter as processor_module

    FakeDocumentConverter.instances.clear()
    monkeypatch.setattr(
        processor_module,
        "DocumentConverter",
        FakeDocumentConverter,
    )
    monkeypatch.setenv("DOCUMENT_PROCESSOR_RAPIDOCR_FORCE_FULL_PAGE_OCR", "1")
    monkeypatch.setenv("DOCUMENT_PROCESSOR_PDF_TABLE_DO_CELL_MATCHING", "0")
    monkeypatch.setenv("DOCUMENT_PROCESSOR_DOCLING_DEVICE", "mps")
    monkeypatch.setenv("DOCUMENT_PROCESSOR_DOCLING_NUM_THREADS", "8")
    monkeypatch.setenv("DOCUMENT_PROCESSOR_PDF_OCR_BATCH_SIZE", "2")
    monkeypatch.setenv("DOCUMENT_PROCESSOR_PDF_LAYOUT_BATCH_SIZE", "3")
    monkeypatch.setenv("DOCUMENT_PROCESSOR_PDF_TABLE_BATCH_SIZE", "5")

    processor_module.build_document_converter()

    converter = FakeDocumentConverter.instances[0]
    format_options = converter.init_kwargs["format_options"]
    pdf_option = format_options[processor_module.InputFormat.PDF]
    pipeline_options = pdf_option.pipeline_options

    assert pipeline_options.ocr_options.force_full_page_ocr is True
    assert pipeline_options.table_structure_options.do_cell_matching is False
    assert pipeline_options.accelerator_options.device == "mps"
    assert pipeline_options.accelerator_options.num_threads == 8
    assert pipeline_options.ocr_batch_size == 2
    assert pipeline_options.layout_batch_size == 3
    assert pipeline_options.table_batch_size == 5


def test_read_source_bytes_restores_file_position():
    from service.document_processor import processor as processor_module

    file_obj = BytesIO(b"%PDF-1.4")
    file_obj.seek(4)

    assert processor_module.read_source_bytes(file_obj) == b"%PDF-1.4"
    assert file_obj.tell() == 0


def test_docling_errors_propagate_without_fallback(monkeypatch):
    from service.document_processor import docling_converter as processor_module

    class RaisingDocumentConverter:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def convert(self, stream):
            raise RuntimeError("docling boom")

    monkeypatch.setattr(
        processor_module,
        "DocumentConverter",
        RaisingDocumentConverter,
    )

    with pytest.raises(RuntimeError, match="docling boom"):
        processor_module.convert_to_docling_document(b"%PDF-1.4", "sample.pdf")


def test_configure_runtime_cache_dirs_sets_repo_local_defaults(monkeypatch):
    from service.document_processor import docling_converter as processor_module

    module_dir = Path(processor_module.__file__).resolve().parent

    monkeypatch.delenv("DOCLING_CACHE_DIR", raising=False)
    monkeypatch.delenv("RAPIDOCR_MODEL_ROOT", raising=False)
    monkeypatch.delenv("HF_HOME", raising=False)
    monkeypatch.delenv("HF_HUB_CACHE", raising=False)
    monkeypatch.delenv("HUGGINGFACE_HUB_CACHE", raising=False)

    processor_module.configure_runtime_cache_dirs()

    assert Path(processor_module.os.environ["DOCLING_CACHE_DIR"]) == module_dir / "models" / "docling"
    assert Path(processor_module.os.environ["RAPIDOCR_MODEL_ROOT"]) == module_dir / "models" / "rapidocr"
    assert Path(processor_module.os.environ["HF_HOME"]) == module_dir / "models" / "huggingface"


def test_configure_runtime_cache_dirs_respects_explicit_overrides(monkeypatch, tmp_path):
    from service.document_processor import docling_converter as processor_module

    custom_docling = tmp_path / "docling"
    custom_rapidocr = tmp_path / "rapidocr"
    custom_hf = tmp_path / "hf"

    monkeypatch.setenv("DOCLING_CACHE_DIR", str(custom_docling))
    monkeypatch.setenv("RAPIDOCR_MODEL_ROOT", str(custom_rapidocr))
    monkeypatch.setenv("HF_HOME", str(custom_hf))
    monkeypatch.delenv("HF_HUB_CACHE", raising=False)
    monkeypatch.delenv("HUGGINGFACE_HUB_CACHE", raising=False)

    processor_module.configure_runtime_cache_dirs()

    assert Path(processor_module.os.environ["DOCLING_CACHE_DIR"]) == custom_docling
    assert Path(processor_module.os.environ["RAPIDOCR_MODEL_ROOT"]) == custom_rapidocr
    assert Path(processor_module.os.environ["HF_HOME"]) == custom_hf
