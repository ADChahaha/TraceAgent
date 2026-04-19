from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from document_processor.schemas import BoundingBox


class NamedBytesIO(BytesIO):
    def __init__(self, data: bytes, filename: str | None = None) -> None:
        super().__init__(data)
        self.filename = filename


class FakeDocument:
    def export_to_markdown(self) -> str:
        return "# 测试标题\n\n第一段正文"

    def iterate_items(self):
        yield (
            SimpleNamespace(
                text="测试标题",
                label="title",
                prov=[],
            ),
            1,
        )
        yield (
            SimpleNamespace(
                text="第一段正文",
                label="text",
                prov=[
                    SimpleNamespace(
                        page_no=2,
                        bbox=SimpleNamespace(l=10.0, t=20.0, r=30.0, b=40.0),
                    )
                ],
            ),
            1,
        )
        yield (
            SimpleNamespace(
                label="table",
                prov=[],
                export_to_markdown=lambda doc: "| 列1 |\n| --- |\n| 值1 |",
            ),
            1,
        )


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


def test_pdf_processor_uses_docling_to_generate_markdown_and_blocks(monkeypatch):
    from document_processor.impl.pdf import processor as processor_module
    from document_processor.impl.pdf.processor import PdfProcessor

    FakeDocumentConverter.instances.clear()
    monkeypatch.setattr(
        processor_module,
        "DocumentConverter",
        FakeDocumentConverter,
    )

    result = PdfProcessor().process(NamedBytesIO(b"%PDF-1.4", filename="sample.pdf"))

    converter = FakeDocumentConverter.instances[0]
    converted_stream = converter.calls[0]

    assert converted_stream.name == "sample.pdf"
    assert converted_stream.stream.read() == b"%PDF-1.4"
    assert result.file_type == "pdf"
    assert result.filename == "sample.pdf"
    assert result.warnings == []
    assert result.markdown == "# 测试标题\n\n第一段正文"
    assert result.md_list == [result.markdown]
    assert [block.text for block in result.blocks] == ["测试标题", "第一段正文", "| 列1 | | --- | | 值1 |"]
    assert [block.kind for block in result.blocks] == ["section_header", "text", "table"]
    assert result.blocks[1].page_no == 2
    assert result.blocks[1].bbox == BoundingBox(10.0, 20.0, 30.0, 40.0)


def test_pdf_processor_passes_document_when_item_markdown_export_requires_it():
    from document_processor.impl.pdf.processor import PdfProcessor

    class ExportNeedsDoc:
        label = "table"
        prov = []

        def export_to_markdown(self, doc):
            assert doc is fake_document
            return "| A |"

    fake_document = SimpleNamespace()

    text = PdfProcessor._extract_text(ExportNeedsDoc(), fake_document)

    assert text == "| A |"


def test_pdf_processor_enables_table_structure_explicitly(monkeypatch):
    from document_processor.impl.pdf import processor as processor_module
    from document_processor.impl.pdf.processor import PdfProcessor

    FakeDocumentConverter.instances.clear()
    monkeypatch.setattr(
        processor_module,
        "DocumentConverter",
        FakeDocumentConverter,
    )

    PdfProcessor()

    converter = FakeDocumentConverter.instances[0]
    format_options = converter.init_kwargs["format_options"]
    pdf_option = format_options[processor_module.InputFormat.PDF]

    assert pdf_option.pipeline_options.do_table_structure is True


def test_pdf_processor_uses_explicit_rapidocr_for_text_extraction(monkeypatch):
    from document_processor.impl.pdf import processor as processor_module
    from document_processor.impl.pdf.processor import PdfProcessor

    FakeDocumentConverter.instances.clear()
    monkeypatch.setattr(
        processor_module,
        "DocumentConverter",
        FakeDocumentConverter,
    )

    PdfProcessor()

    converter = FakeDocumentConverter.instances[0]
    format_options = converter.init_kwargs["format_options"]
    pdf_option = format_options[processor_module.InputFormat.PDF]
    ocr_options = pdf_option.pipeline_options.ocr_options
    repo_pdf_dir = Path("./agent/document_processor/impl/pdf/models")

    assert type(ocr_options).__name__ == "RapidOcrOptions"
    assert ocr_options.backend == "torch"
    assert ocr_options.lang == ["chinese", "english"]
    assert Path(ocr_options.rapidocr_params["Global.model_root_dir"]) == (
        repo_pdf_dir / "rapidocr"
    )
    assert Path(ocr_options.rec_keys_path) == (repo_pdf_dir / "rapidocr" / "ppocr_keys_v1.txt")


def test_pdf_processor_uses_default_filename_when_input_has_no_name(monkeypatch):
    from document_processor.impl.pdf import processor as processor_module
    from document_processor.impl.pdf.processor import PdfProcessor

    FakeDocumentConverter.instances.clear()
    monkeypatch.setattr(
        processor_module,
        "DocumentConverter",
        FakeDocumentConverter,
    )

    result = PdfProcessor().process(BytesIO(b"%PDF-1.4"))

    converter = FakeDocumentConverter.instances[0]
    converted_stream = converter.calls[0]

    assert converted_stream.name == "document.pdf"
    assert result.filename == "document.pdf"


def test_process_routes_pdf_files_to_docling_processor_by_default(monkeypatch):
    from document_processor import processor as entrypoint_module
    from document_processor.impl.interface import InternalProcessorInterface
    from document_processor.impl.pdf import processor as processor_module
    from document_processor.impl.pdf.processor import PdfProcessor
    from document_processor.types import FileType

    FakeDocumentConverter.instances.clear()
    monkeypatch.setattr(
        processor_module,
        "DocumentConverter",
        FakeDocumentConverter,
    )

    original_types = InternalProcessorInterface._processor_types.copy()
    original_instances = InternalProcessorInterface._processor_instances.copy()
    original_defaults_flag = InternalProcessorInterface._defaults_registered
    try:
        InternalProcessorInterface._processor_types.clear()
        InternalProcessorInterface._processor_instances.clear()
        InternalProcessorInterface._defaults_registered = False

        result = entrypoint_module.process(
            NamedBytesIO(b"%PDF-1.4", filename="sample.pdf"),
        )

        assert result.file_type == "pdf"
        assert InternalProcessorInterface._processor_types[FileType.PDF] is PdfProcessor
    finally:
        InternalProcessorInterface._processor_types.clear()
        InternalProcessorInterface._processor_types.update(original_types)
        InternalProcessorInterface._processor_instances.clear()
        InternalProcessorInterface._processor_instances.update(original_instances)
        InternalProcessorInterface._defaults_registered = original_defaults_flag


def test_pdf_processor_propagates_docling_errors_without_fallback(monkeypatch):
    from document_processor.impl.pdf import processor as processor_module
    from document_processor.impl.pdf.processor import PdfProcessor

    class RaisingDocumentConverter:
        def __init__(self, *args, **kwargs):
            pass

        def convert(self, stream):
            raise RuntimeError("docling boom")

    monkeypatch.setattr(
        processor_module,
        "DocumentConverter",
        RaisingDocumentConverter,
    )

    file_obj = NamedBytesIO(b"%PDF-1.4", filename="sample.pdf")

    try:
        PdfProcessor().process(file_obj)
    except RuntimeError as exc:
        assert str(exc) == "docling boom"
    else:
        raise AssertionError("Expected docling error to be raised directly.")


def test_pdf_processor_sets_repo_local_cache_dirs_by_default(monkeypatch):
    from document_processor.impl.pdf import processor as processor_module

    repo_pdf_dir = Path("./agent/document_processor/impl/pdf/models")

    monkeypatch.delenv("DOCLING_CACHE_DIR", raising=False)
    monkeypatch.delenv("HF_HOME", raising=False)
    monkeypatch.delenv("HF_HUB_CACHE", raising=False)
    monkeypatch.delenv("HUGGINGFACE_HUB_CACHE", raising=False)

    processor_module._configure_runtime_cache_dirs()

    assert Path(processor_module.os.environ["DOCLING_CACHE_DIR"]) == repo_pdf_dir / "docling"
    assert Path(processor_module.os.environ["HF_HOME"]) == repo_pdf_dir / "huggingface"
    assert Path(processor_module.os.environ["RAPIDOCR_MODEL_ROOT"]) == repo_pdf_dir / "rapidocr"


def test_pdf_processor_respects_explicit_cache_env_overrides(monkeypatch, tmp_path):
    from document_processor.impl.pdf import processor as processor_module

    custom_docling_cache = tmp_path / "docling-cache"
    custom_hf_home = tmp_path / "hf-home"
    custom_rapidocr_root = tmp_path / "rapidocr-models"

    monkeypatch.setenv("DOCLING_CACHE_DIR", str(custom_docling_cache))
    monkeypatch.setenv("HF_HOME", str(custom_hf_home))
    monkeypatch.setenv("RAPIDOCR_MODEL_ROOT", str(custom_rapidocr_root))
    monkeypatch.delenv("HF_HUB_CACHE", raising=False)
    monkeypatch.delenv("HUGGINGFACE_HUB_CACHE", raising=False)

    processor_module._configure_runtime_cache_dirs()

    assert Path(processor_module.os.environ["DOCLING_CACHE_DIR"]) == custom_docling_cache
    assert Path(processor_module.os.environ["HF_HOME"]) == custom_hf_home
    assert Path(processor_module.os.environ["RAPIDOCR_MODEL_ROOT"]) == custom_rapidocr_root
