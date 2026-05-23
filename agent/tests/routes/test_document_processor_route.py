from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from service.document_processor.schemas import ProcessResult
from main import create_app


def test_document_processor_capabilities_route_reports_pdf_and_docx_processors():
    client = TestClient(create_app())

    response = client.get("/v1/ocr/capabilities")

    assert response.status_code == 200
    payload = response.json()
    assert payload["supported_file_types"] == ["pdf", "docx"]
    assert payload["implemented_file_types"] == ["pdf", "docx"]
    assert payload["engine"] == "mineru-pipeline,python-docx"


def test_document_processor_route_uses_public_processor_exception_contract():
    import routes.document_processor as route_module

    source = Path(route_module.__file__).read_text()

    assert "service.document_processor.impl" not in source
    assert "InvalidFileObjectError" in source
    assert "UnsupportedFileTypeError" in source


def test_document_processor_process_route_calls_business_processor(monkeypatch):
    from service.document_processor import processor as processor_module

    seen_call: dict[str, object] = {}

    def fake_process(file_obj, file_type=None):
        seen_call["file_obj"] = file_obj
        seen_call["file_type"] = file_type
        seen_call["prefix"] = file_obj.read(4)
        return ProcessResult(
            filename="sample.pdf",
            html="<html><body>正文</body></html>",
            markdown="正文",
            md_list=["正文"],
            blocks=[{"block_id": "p001_b000", "text": "正文", "page_no": 1, "kind": "text"}],
            semantic_document={
                "sections": [{"section_id": "sec_001", "text": "正文"}],
                "blocks": [{"block_id": "p001_b000", "text": "正文"}],
                "inlines": [],
            },
            meta_info={"engine": "fake"},
            warnings=["fake-warning"],
        )

    monkeypatch.setattr(processor_module, "process", fake_process)

    client = TestClient(create_app())
    response = client.post(
        "/v1/document-processor/process",
        files={"file": ("sample.pdf", b"%PDF-1.4", "application/pdf")},
        data={"file_type": "pdf"},
    )

    assert response.status_code == 200
    assert seen_call["file_type"] == "pdf"
    assert getattr(seen_call["file_obj"], "filename") == "sample.pdf"
    assert seen_call["prefix"] == b"%PDF"
    assert response.json() == {
        "filename": "sample.pdf",
        "html": "<html><body>正文</body></html>",
        "display_html": None,
        "markdown": "正文",
        "md_list": ["正文"],
        "blocks": [
            {
                "block_id": "p001_b000",
                "text": "正文",
                "page_no": 1,
                "kind": "text",
            }
        ],
        "semantic_document": {
            "sections": [{"section_id": "sec_001", "text": "正文"}],
            "blocks": [{"block_id": "p001_b000", "text": "正文"}],
            "inlines": [],
        },
        "meta_info": {"engine": "fake"},
        "warnings": ["fake-warning"],
    }


def test_document_processor_docx_route_calls_docx_processor(monkeypatch):
    from service.document_processor import docx_processor

    seen_call: dict[str, object] = {}

    def fake_process_docx(file_obj):
        seen_call["file_obj"] = file_obj
        seen_call["prefix"] = file_obj.read(4)
        return ProcessResult(
            filename="sample.docx",
            html='<section id="docx_b001_section"><h1 id="docx_b001">Overview</h1></section>',
            display_html='<html><body><h1 id="docx_b001">Overview</h1></body></html>',
            markdown="# Overview",
            md_list=["Overview"],
            blocks=[
                {
                    "block_id": "docx_b001",
                    "text": "Overview",
                    "page_no": None,
                    "kind": "heading",
                }
            ],
            semantic_document={
                "sections": [{"section_id": "docx_b001", "title": "Overview", "level": 1}],
                "blocks": [{"block_id": "docx_b001", "text": "Overview"}],
                "inlines": [],
            },
            meta_info={"engine": "python-docx"},
            warnings=[],
        )

    monkeypatch.setattr(docx_processor, "process_docx", fake_process_docx)

    client = TestClient(create_app())
    response = client.post(
        "/v1/document-processor/docx/process",
        files={
            "file": (
                "sample.docx",
                b"PK\x03\x04 fake",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )

    assert response.status_code == 200
    assert getattr(seen_call["file_obj"], "filename") == "sample.docx"
    assert seen_call["prefix"] == b"PK\x03\x04"
    assert response.json() == {
        "filename": "sample.docx",
        "html": '<section id="docx_b001_section"><h1 id="docx_b001">Overview</h1></section>',
        "display_html": '<html><body><h1 id="docx_b001">Overview</h1></body></html>',
        "markdown": "# Overview",
        "md_list": ["Overview"],
        "blocks": [
            {
                "block_id": "docx_b001",
                "text": "Overview",
                "page_no": None,
                "kind": "heading",
            }
        ],
        "semantic_document": {
            "sections": [{"section_id": "docx_b001", "title": "Overview", "level": 1}],
            "blocks": [{"block_id": "docx_b001", "text": "Overview"}],
            "inlines": [],
        },
        "meta_info": {"engine": "python-docx"},
        "warnings": [],
    }
