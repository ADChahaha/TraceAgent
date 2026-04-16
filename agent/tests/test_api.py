from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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
        ocr_router,
        "_resolve_docling_artifacts_path",
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

    monkeypatch.setattr(ocr_router, "_process_document", fake_process)

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

    monkeypatch.setattr(ocr_router, "_process_document", raise_unsupported_type)

    response = client.post(
        "/v1/ocr/process",
        data={"file_type": "txt"},
        files={"file": ("sample.txt", b"hello", "text/plain")},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Unsupported file type: txt"}
