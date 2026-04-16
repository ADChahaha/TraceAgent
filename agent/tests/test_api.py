from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
import types

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _install_docling_stub() -> None:
    if importlib.util.find_spec("docling") is not None or "docling" in sys.modules:
        return

    docling_module = types.ModuleType("docling")
    docling_module.__path__ = []

    backend_module = types.ModuleType("docling.backend")
    backend_module.__path__ = []
    pypdfium_backend_module = types.ModuleType("docling.backend.pypdfium2_backend")

    datamodel_module = types.ModuleType("docling.datamodel")
    datamodel_module.__path__ = []
    base_models_module = types.ModuleType("docling.datamodel.base_models")
    pipeline_options_module = types.ModuleType("docling.datamodel.pipeline_options")

    document_converter_module = types.ModuleType("docling.document_converter")

    class DocumentStream:
        def __init__(self, name: str, stream):
            self.name = name
            self.stream = stream

    class InputFormat:
        PDF = "pdf"

    class PdfPipelineOptions:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    class RapidOcrOptions:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    class DocumentConverter:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        def convert(self, *args, **kwargs):
            raise RuntimeError("docling stub should be monkeypatched in tests")

    class PdfFormatOption:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    class PyPdfiumDocumentBackend:
        pass

    base_models_module.DocumentStream = DocumentStream
    base_models_module.InputFormat = InputFormat
    pipeline_options_module.PdfPipelineOptions = PdfPipelineOptions
    pipeline_options_module.RapidOcrOptions = RapidOcrOptions
    document_converter_module.DocumentConverter = DocumentConverter
    document_converter_module.PdfFormatOption = PdfFormatOption
    pypdfium_backend_module.PyPdfiumDocumentBackend = PyPdfiumDocumentBackend

    sys.modules["docling"] = docling_module
    sys.modules["docling.backend"] = backend_module
    sys.modules["docling.backend.pypdfium2_backend"] = pypdfium_backend_module
    sys.modules["docling.datamodel"] = datamodel_module
    sys.modules["docling.datamodel.base_models"] = base_models_module
    sys.modules["docling.datamodel.pipeline_options"] = pipeline_options_module
    sys.modules["docling.document_converter"] = document_converter_module


_install_docling_stub()

import main
import routes.ocr_processor as ocr_router
from ocr_processor.schemas import BoundingBox, ContentBlock, ProcessResult
from ocr_processor.types import FileType, UnsupportedFileTypeError

client = TestClient(main.app)


def test_healthz_returns_ok():
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_capabilities_reports_supported_file_types(tmp_path, monkeypatch):
    artifacts_path = tmp_path / "docling-models"
    artifacts_path.mkdir()

    monkeypatch.setattr(
        ocr_router.pdf_docling_adapter,
        "resolve_docling_artifacts_path",
        lambda: artifacts_path,
    )

    response = client.get("/v1/ocr/capabilities")

    assert response.status_code == 200
    assert response.json() == {
        "supported_file_types": ["pdf", "doc", "docx"],
        "implemented_file_types": ["pdf", "docx"],
        "docling_artifacts_path": str(artifacts_path),
        "docling_artifacts_available": True,
    }


def test_process_endpoint_returns_serialized_result(monkeypatch):
    captured: dict[str, object] = {}

    def fake_process(file_obj, file_type=None):
        captured["filename"] = file_obj.filename
        captured["content_type"] = file_obj.content_type
        captured["body"] = file_obj.file.read()
        file_obj.file.seek(0)
        captured["file_type"] = file_type

        return ProcessResult(
            file_type=FileType.PDF,
            filename="sample.pdf",
            md_list=["Hello OCR"],
            markdown="Hello OCR",
            blocks=[
                ContentBlock(
                    text="Hello OCR",
                    page_no=1,
                    bbox=BoundingBox(x0=1.0, y0=2.0, x1=3.0, y1=4.0),
                    kind="text",
                    meta_info={"md": "Hello OCR"},
                )
            ],
            meta_info={"engine": "stub", "fallback_used": False},
            warnings=[],
        )

    monkeypatch.setattr(ocr_router, "process_document", fake_process)

    response = client.post(
        "/v1/ocr/process",
        data={"file_type": "pdf"},
        files={"file": ("sample.pdf", b"%PDF-1.4", "application/pdf")},
    )

    assert response.status_code == 200
    assert captured == {
        "filename": "sample.pdf",
        "content_type": "application/pdf",
        "body": b"%PDF-1.4",
        "file_type": "pdf",
    }
    assert response.json() == {
        "file_type": "pdf",
        "filename": "sample.pdf",
        "md_list": ["Hello OCR"],
        "markdown": "Hello OCR",
        "blocks": [
            {
                "text": "Hello OCR",
                "page_no": 1,
                "bbox": {"x0": 1.0, "y0": 2.0, "x1": 3.0, "y1": 4.0},
                "kind": "text",
                "meta_info": {"md": "Hello OCR"},
            }
        ],
        "meta_info": {"engine": "stub", "fallback_used": False},
        "warnings": [],
    }


def test_process_endpoint_maps_unsupported_type_to_422(monkeypatch):
    def raise_unsupported_type(file_obj, file_type=None):
        raise UnsupportedFileTypeError("Unsupported file type: txt")

    monkeypatch.setattr(ocr_router, "process_document", raise_unsupported_type)

    response = client.post(
        "/v1/ocr/process",
        data={"file_type": "txt"},
        files={"file": ("sample.txt", b"hello", "text/plain")},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Unsupported file type: txt"}
