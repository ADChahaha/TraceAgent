from __future__ import annotations

from fastapi.testclient import TestClient

from service.document_processor.schemas import ContentBlock, ProcessResult
from main import create_app


def test_document_processor_process_route_calls_business_processor(monkeypatch):
    from service.document_processor import processor as processor_module

    seen_call: dict[str, object] = {}

    def fake_process(file_obj, file_type=None):
        seen_call["file_obj"] = file_obj
        seen_call["file_type"] = file_type
        seen_call["prefix"] = file_obj.read(4)
        return ProcessResult(
            file_type="pdf",
            filename="sample.pdf",
            md_list=["正文"],
            markdown="正文",
            blocks=[ContentBlock(text="正文", page_no=1)],
            meta_info={"processor": "fake"},
            warnings=["测试 warning"],
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
        "file_type": "pdf",
        "filename": "sample.pdf",
        "md_list": ["正文"],
        "markdown": "正文",
        "blocks": [
            {
                "text": "正文",
                "page_no": 1,
                "bbox": None,
                "kind": "text",
                "meta_info": {},
            }
        ],
        "meta_info": {"processor": "fake"},
        "warnings": ["测试 warning"],
    }
