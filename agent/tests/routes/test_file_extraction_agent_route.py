from __future__ import annotations

from fastapi.testclient import TestClient

from service.file_extraction_agent.schemas import (
    EvidenceSummary,
    ExtractionContent,
    ExtractionResult,
    ExtractionTrace,
    FieldDefinition,
    FieldResult,
    FieldTrace,
    RunOptions,
    TaskSpec,
)
from main import create_app


def test_file_extraction_agent_route_calls_business_extractor(monkeypatch):
    from service.file_extraction_agent import processor as processor_module

    seen_call: dict[str, object] = {}

    def fake_extract(**kwargs):
        seen_call.update(kwargs)
        return ExtractionResult(
            result=ExtractionContent(
                fields=[
                    FieldResult(
                        field_name="invoice_no",
                        status="resolved",
                        value="INV-001",
                    )
                ]
            ),
            trace=ExtractionTrace(
                fields=[
                    FieldTrace(
                        field_name="invoice_no",
                        status="resolved",
                        evidence=EvidenceSummary(
                            block_ids=["b1"],
                            texts=["发票号 INV-001"],
                            status="evidence_found",
                        ),
                        related_fields=["invoice_no"],
                        reason="测试路由已调用业务抽取入口",
                    )
                ],
                metadata={"source": "route-test"},
            ),
        )

    monkeypatch.setattr(processor_module, "extract", fake_extract)

    client = TestClient(create_app())
    response = client.post(
        "/v1/file-extraction-agent/extract",
        json={
            "blocks": [
                {
                    "document_id": "doc-1",
                    "block_id": "b1",
                    "text": "发票号 INV-001",
                    "page_no": 1,
                }
            ],
            "markdown": "发票号 INV-001",
            "task_spec": {
                "task_name": "invoice",
                "fields": [
                    {
                        "field_name": "invoice_no",
                        "display_name": "发票号",
                        "type": "string",
                        "required": True,
                    }
                ],
            },
            "metadata": {"source": "backend"},
        },
    )

    assert response.status_code == 200
    assert seen_call["blocks"][0].document_id == "doc-1"
    assert seen_call["markdown"] == "发票号 INV-001"
    assert seen_call["task_spec"] == TaskSpec(
        task_name="invoice",
        fields=[
            FieldDefinition(
                field_name="invoice_no",
                display_name="发票号",
                type="string",
                required=True,
            )
        ],
    )
    assert seen_call["metadata"] == {"source": "backend"}
    assert seen_call["structured_output_strategy"] == "tool_call"
    assert response.json()["result"]["fields"][0]["value"] == "INV-001"


def test_file_extraction_agent_route_passes_run_options_to_business_extractor(monkeypatch):
    from service.file_extraction_agent import processor as processor_module

    seen_call: dict[str, object] = {}

    def fake_extract(**kwargs):
        seen_call.update(kwargs)
        return ExtractionResult(
            result=ExtractionContent(fields=[]),
            trace=ExtractionTrace(fields=[]),
        )

    monkeypatch.setattr(processor_module, "extract", fake_extract)

    client = TestClient(create_app())
    response = client.post(
        "/v1/file-extraction-agent/extract",
        json={
            "blocks": [
                {
                    "document_id": "doc-1",
                    "block_id": "b1",
                    "text": "发票号 INV-001",
                }
            ],
            "task_spec": {
                "task_name": "invoice",
                "fields": [
                    {
                        "field_name": "invoice_no",
                        "display_name": "发票号",
                        "type": "string",
                    }
                ],
            },
            "run_options": {
                "max_prompt_blocks": 12,
                "max_resolution_candidates": 4,
            },
        },
    )

    assert response.status_code == 200
    assert seen_call["run_options"] == RunOptions(
        max_prompt_blocks=12,
        max_resolution_candidates=4,
    )
    assert type(seen_call["run_options"]).__module__ == "service.file_extraction_agent.schemas"


def test_file_extraction_agent_route_passes_stage_model_overrides(monkeypatch):
    from service.file_extraction_agent import processor as processor_module

    seen_call: dict[str, object] = {}

    def fake_extract(**kwargs):
        seen_call.update(kwargs)
        return ExtractionResult(
            result=ExtractionContent(fields=[]),
            trace=ExtractionTrace(fields=[]),
        )

    monkeypatch.setattr(processor_module, "extract", fake_extract)

    client = TestClient(create_app())
    response = client.post(
        "/v1/file-extraction-agent/extract",
        json={
            "blocks": [
                {
                    "document_id": "doc-1",
                    "block_id": "b1",
                    "text": "发票号 INV-001",
                }
            ],
            "task_spec": {
                "task_name": "invoice",
                "fields": [
                    {
                        "field_name": "invoice_no",
                        "display_name": "发票号",
                        "type": "string",
                    }
                ],
            },
            "model": "default-model",
            "broad_model": "small-broad-model",
            "resolution_model": "strong-resolution-model",
        },
    )

    assert response.status_code == 200
    assert seen_call["model"] == "default-model"
    assert seen_call["broad_model"] == "small-broad-model"
    assert seen_call["resolution_model"] == "strong-resolution-model"


def test_file_extraction_agent_route_rejects_json_schema_and_auto_strategies(monkeypatch):
    from service.file_extraction_agent import processor as processor_module

    seen_calls: list[dict[str, object]] = []

    def fake_extract(**kwargs):
        seen_calls.append(kwargs)
        return ExtractionResult(
            result=ExtractionContent(fields=[]),
            trace=ExtractionTrace(fields=[]),
        )

    monkeypatch.setattr(processor_module, "extract", fake_extract)

    client = TestClient(create_app())
    for strategy in ["json_schema", "auto"]:
        response = client.post(
            "/v1/file-extraction-agent/extract",
            json={
                "blocks": [
                    {
                        "document_id": "doc-1",
                        "block_id": "b1",
                        "text": "发票号 INV-001",
                    }
                ],
                "task_spec": {
                    "task_name": "invoice",
                    "fields": [
                        {
                            "field_name": "invoice_no",
                            "display_name": "发票号",
                            "type": "string",
                        }
                    ],
                },
                "structured_output_strategy": strategy,
            },
        )

        assert response.status_code == 422

    assert seen_calls == []


def test_file_extraction_agent_route_returns_422_for_missing_task_spec(monkeypatch):
    from service.file_extraction_agent import processor as processor_module

    def fake_extract(**kwargs):
        del kwargs
        raise ValueError("task_spec is required")

    monkeypatch.setattr(processor_module, "extract", fake_extract)

    client = TestClient(create_app())
    response = client.post(
        "/v1/file-extraction-agent/extract",
        json={
            "blocks": [
                {
                    "document_id": "doc-1",
                    "text": "发票号 INV-001",
                }
            ],
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "task_spec is required"


def test_file_extraction_agent_route_rejects_task_spec_name_payload():
    client = TestClient(create_app())
    response = client.post(
        "/v1/file-extraction-agent/extract",
        json={
            "blocks": [
                {
                    "document_id": "doc-1",
                    "text": "发票号 INV-001",
                }
            ],
            "task_spec_name": "invoice",
        },
    )

    assert response.status_code == 422
