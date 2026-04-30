import sys
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from service.document_processor.schemas import BoundingBox


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
    from service.document_processor.impl.pdf import processor as processor_module
    from service.document_processor.impl.pdf.processor import PdfProcessor

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
    assert [block.text for block in result.blocks] == [
        "测试标题",
        "第一段正文",
        "| 列1 | | --- | | 值1 |",
    ]
    assert [block.kind for block in result.blocks] == ["section_header", "text", "table"]
    assert result.blocks[1].page_no == 2
    assert result.blocks[1].bbox == BoundingBox(10.0, 20.0, 30.0, 40.0)


def test_pdf_processor_passes_document_when_item_markdown_export_requires_it():
    from service.document_processor.impl.pdf.processor import PdfProcessor

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
    from service.document_processor.impl.pdf import processor as processor_module
    from service.document_processor.impl.pdf.processor import PdfProcessor

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
    from service.document_processor.impl.pdf import processor as processor_module
    from service.document_processor.impl.pdf.processor import PdfProcessor

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
    repo_pdf_dir = Path(processor_module.__file__).resolve().parent / "models"

    assert type(ocr_options).__name__ == "RapidOcrOptions"
    assert ocr_options.backend == "torch"
    assert ocr_options.lang == ["chinese", "english"]
    assert Path(ocr_options.rapidocr_params["Global.model_root_dir"]) == (
        repo_pdf_dir / "rapidocr"
    )
    assert Path(ocr_options.rec_keys_path) == (repo_pdf_dir / "rapidocr" / "ppocr_keys_v1.txt")


def test_pdf_processor_uses_default_filename_when_input_has_no_name(monkeypatch):
    from service.document_processor.impl.pdf import processor as processor_module
    from service.document_processor.impl.pdf.processor import PdfProcessor

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
    from service.document_processor import processor as entrypoint_module
    from service.document_processor.impl.interface import InternalProcessorInterface
    from service.document_processor.impl.pdf import processor as processor_module
    from service.document_processor.impl.pdf.processor import PdfProcessor
    from service.document_processor.types import FileType

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


def test_process_can_route_pdf_files_to_paddle_processor(monkeypatch):
    from service.document_processor.impl.interface import InternalProcessorInterface
    from service.document_processor.impl.pdf.paddle_processor import PdfPaddleProcessor
    from service.document_processor.types import FileType

    monkeypatch.setenv("DOCUMENT_PROCESSOR_PDF_ENGINE", "pdf-paddle")

    original_types = InternalProcessorInterface._processor_types.copy()
    original_instances = InternalProcessorInterface._processor_instances.copy()
    original_defaults_flag = InternalProcessorInterface._defaults_registered
    try:
        InternalProcessorInterface._processor_types.clear()
        InternalProcessorInterface._processor_instances.clear()
        InternalProcessorInterface._defaults_registered = False

        InternalProcessorInterface._ensure_default_processors_registered()

        assert InternalProcessorInterface._processor_types[FileType.PDF] is PdfPaddleProcessor
    finally:
        InternalProcessorInterface._processor_types.clear()
        InternalProcessorInterface._processor_types.update(original_types)
        InternalProcessorInterface._processor_instances.clear()
        InternalProcessorInterface._processor_instances.update(original_instances)
        InternalProcessorInterface._defaults_registered = original_defaults_flag


def test_pdf_paddle_processor_generates_structured_markdown_blocks(monkeypatch):
    from service.document_processor.impl.pdf.paddle_processor import PdfPaddleProcessor

    class FakeStructureResult:
        @property
        def markdown(self):
            return {
                "markdown_texts": (
                    "名单说明\n\n"
                    "<table><tr><th>序号</th><th>作品类型</th><th>论文题目</th></tr>"
                    "<tr><td>1</td><td>学术论文</td><td>测试论文</td></tr></table>"
                )
            }

        @property
        def json(self):
            return {
                "res": {
                    "parsing_res_list": [
                        {
                            "block_label": "text",
                            "block_content": "名单说明",
                            "block_bbox": [10, 20, 110, 36],
                            "block_id": 1,
                            "block_order": 1,
                        },
                        {
                            "block_label": "table",
                            "block_content": (
                                "<table><tr><th>序号</th><th>作品类型</th><th>论文题目</th></tr>"
                                "<tr><td>1</td><td>学术论文</td><td>测试论文</td></tr></table>"
                            ),
                            "block_bbox": [10, 45, 310, 120],
                            "block_id": 2,
                            "block_order": 2,
                        },
                    ]
                }
            }

    class FakePaddleStructure:
        def __init__(self) -> None:
            self.calls = []

        def predict(self, image, **kwargs):
            self.calls.append({"image": image, **kwargs})
            return [FakeStructureResult()]

    fake_structure = FakePaddleStructure()
    processor = PdfPaddleProcessor(ocr_client=fake_structure, render_scale=1.5)
    monkeypatch.setattr(
        processor,
        "_render_pdf_pages",
        lambda source_bytes: ["rendered-page"],
    )

    result = processor.process(NamedBytesIO(b"%PDF-1.4", filename="sample.pdf"))

    assert fake_structure.calls == [
        {
            "image": "rendered-page",
            "use_table_recognition": True,
            "format_block_content": True,
        }
    ]
    assert result.file_type == "pdf"
    assert result.filename == "sample.pdf"
    assert result.markdown == (
        "名单说明\n\n"
        "| 序号 | 作品类型 | 论文题目 |\n"
        "| --- | --- | --- |\n"
        "| 1 | 学术论文 | 测试论文 |"
    )
    assert result.md_list == [result.markdown]
    assert [block.text for block in result.blocks] == [
        "名单说明",
        "| 序号 | 作品类型 | 论文题目 |\n| --- | --- | --- |\n| 1 | 学术论文 | 测试论文 |",
    ]
    assert [block.kind for block in result.blocks] == ["text", "table"]
    assert [block.page_no for block in result.blocks] == [1, 1]
    assert result.blocks[0].bbox == BoundingBox(10.0, 20.0, 110.0, 36.0)
    assert result.blocks[0].meta_info == {
        "ocr_engine": "paddleocr",
        "paddle_pipeline": "PPStructureV3",
        "block_label": "text",
        "block_id": 1,
        "block_order": 1,
        "render_scale": 1.5,
    }
    assert result.meta_info["ocr_engine"] == "paddleocr"
    assert result.meta_info["paddle_pipeline"] == "PPStructureV3"
    assert result.meta_info["block_count"] == 2
    assert result.meta_info["page_count"] == 1


def test_pdf_paddle_processor_keeps_text_line_fallback_for_plain_ocr_result(monkeypatch):
    from service.document_processor.impl.pdf.paddle_processor import PdfPaddleProcessor

    class FakePaddleOcr:
        def __init__(self) -> None:
            self.calls = []

        def predict(self, image):
            self.calls.append({"method": "predict", "image": image})
            return [
                {
                    "rec_texts": ["第三行"],
                    "rec_scores": [0.88],
                    "rec_boxes": [[1, 2, 31, 12]],
                }
            ]

        def ocr(self, image, cls=True):
            self.calls.append({"method": "ocr", "image": image, "cls": cls})
            return []

    fake_ocr = FakePaddleOcr()
    processor = PdfPaddleProcessor(ocr_client=fake_ocr)
    monkeypatch.setattr(
        processor,
        "_render_pdf_pages",
        lambda source_bytes: ["rendered-page"],
    )

    result = processor.process(NamedBytesIO(b"%PDF-1.4", filename="sample.pdf"))

    assert fake_ocr.calls == [{"method": "predict", "image": "rendered-page"}]
    assert result.markdown == "第三行"
    assert result.blocks[0].bbox == BoundingBox(1.0, 2.0, 31.0, 12.0)
    assert result.blocks[0].kind == "text_line"


def test_pdf_paddle_processor_builds_ppstructure_with_table_recognition(monkeypatch):
    from service.document_processor.impl.pdf.paddle_processor import PdfPaddleProcessor

    calls = []

    class FakePaddleStructure:
        def __init__(self, **kwargs) -> None:
            calls.append(kwargs)

    monkeypatch.setitem(
        sys.modules,
        "paddleocr",
        SimpleNamespace(PPStructureV3=FakePaddleStructure),
    )

    client = PdfPaddleProcessor._build_ocr_client()

    assert isinstance(client, FakePaddleStructure)
    assert calls == [
        {
            "lang": "ch",
            "ocr_version": "PP-OCRv4",
            "use_doc_orientation_classify": False,
            "use_doc_unwarping": False,
            "use_textline_orientation": False,
            "use_table_recognition": True,
            "format_block_content": True,
        }
    ]


def test_pdf_paddle_processor_sets_repo_local_paddlex_cache(monkeypatch):
    from service.document_processor.impl.pdf import processor as processor_module
    from service.document_processor.impl.pdf.paddle_processor import PdfPaddleProcessor

    class FakePaddleStructure:
        def __init__(self, **kwargs) -> None:
            pass

    monkeypatch.delenv("PADDLE_PDX_CACHE_HOME", raising=False)
    monkeypatch.setitem(
        sys.modules,
        "paddleocr",
        SimpleNamespace(PPStructureV3=FakePaddleStructure),
    )

    PdfPaddleProcessor._build_ocr_client()

    assert Path(processor_module.os.environ["PADDLE_PDX_CACHE_HOME"]) == (
        Path(processor_module.__file__).resolve().parent / "models" / "paddlex"
    )


def test_pdf_paddle_processor_respects_paddle_ocr_version_override(monkeypatch):
    from service.document_processor.impl.pdf.paddle_processor import PdfPaddleProcessor

    calls = []

    class FakePaddleStructure:
        def __init__(self, **kwargs) -> None:
            calls.append(kwargs)

    monkeypatch.setenv("DOCUMENT_PROCESSOR_PADDLE_OCR_VERSION", "PP-OCRv5")
    monkeypatch.setitem(
        sys.modules,
        "paddleocr",
        SimpleNamespace(PPStructureV3=FakePaddleStructure),
    )

    PdfPaddleProcessor._build_ocr_client()

    assert calls[0]["ocr_version"] == "PP-OCRv5"


def test_pdf_processor_propagates_docling_errors_without_fallback(monkeypatch):
    from service.document_processor.impl.pdf import processor as processor_module
    from service.document_processor.impl.pdf.processor import PdfProcessor

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
    from service.document_processor.impl.pdf import processor as processor_module

    repo_pdf_dir = Path(processor_module.__file__).resolve().parent / "models"

    monkeypatch.delenv("DOCLING_CACHE_DIR", raising=False)
    monkeypatch.delenv("HF_HOME", raising=False)
    monkeypatch.delenv("HF_HUB_CACHE", raising=False)
    monkeypatch.delenv("HUGGINGFACE_HUB_CACHE", raising=False)

    processor_module._configure_runtime_cache_dirs()

    assert Path(processor_module.os.environ["DOCLING_CACHE_DIR"]) == repo_pdf_dir / "docling"
    assert Path(processor_module.os.environ["HF_HOME"]) == repo_pdf_dir / "huggingface"
    assert Path(processor_module.os.environ["RAPIDOCR_MODEL_ROOT"]) == repo_pdf_dir / "rapidocr"


def test_pdf_processor_respects_explicit_cache_env_overrides(monkeypatch, tmp_path):
    from service.document_processor.impl.pdf import processor as processor_module

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
