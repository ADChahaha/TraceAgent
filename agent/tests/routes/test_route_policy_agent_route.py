from __future__ import annotations

from fastapi.testclient import TestClient

from main import create_app
from service.route_policy_agent.schemas import FieldRouteDecision, RoutePolicyResult


def test_route_policy_agent_route_calls_business_evaluator(monkeypatch):
    from service.route_policy_agent import processor as processor_module

    seen_call: dict[str, object] = {}

    def fake_evaluate(**kwargs):
        seen_call.update(kwargs)
        return RoutePolicyResult(
            field_routes=[
                FieldRouteDecision(
                    field_name="invoice_no",
                    route="accept",
                    route_reason="路由测试已调用业务入口",
                    needs_review=False,
                )
            ],
            metadata={"source": "route-test"},
        )

    monkeypatch.setattr(processor_module, "evaluate", fake_evaluate)

    client = TestClient(create_app())
    response = client.post(
        "/v1/route-policy-agent/evaluate",
        json={
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
            "field_outputs": [
                {
                    "field_name": "invoice_no",
                    "status": "resolved",
                    "value": "INV-001",
                }
            ],
            "refs_with_text": [
                {
                    "field_name": "invoice_no",
                    "refs": [
                        {
                            "document_id": "doc-1",
                            "page": 1,
                            "block_id": "b1",
                            "text": "发票号码：INV-001",
                        }
                    ],
                }
            ],
            "field_processes": [
                {
                    "field_name": "invoice_no",
                    "broad_extraction": {
                        "search_queries": ["发票号 OR 发票号码"],
                        "candidate_action_count": 1,
                        "finish_reason": "候选足够，结束 broad",
                    },
                    "field_resolution": {
                        "search_queries": [],
                        "final_decision_used": True,
                        "reason": "候选证据支持字段值",
                    },
                }
            ],
            "base_url": "https://llm.example.com/v1",
            "openai_api_key": "test-key",
            "model": "small-route-model",
            "structured_output_strategy": "tool_call",
        },
    )

    assert response.status_code == 200
    assert seen_call["task_spec"].fields[0].field_name == "invoice_no"
    assert seen_call["field_outputs"][0].value == "INV-001"
    assert seen_call["refs_with_text"][0].refs[0].text == "发票号码：INV-001"
    assert seen_call["field_processes"][0].broad_extraction.search_queries == [
        "发票号 OR 发票号码"
    ]
    assert seen_call["base_url"] == "https://llm.example.com/v1"
    assert seen_call["openai_api_key"] == "test-key"
    assert seen_call["structured_output_strategy"] == "tool_call"
    assert "policy_options" not in seen_call
    assert response.json()["field_routes"][0]["route"] == "accept"


def test_route_policy_agent_route_rejects_policy_options_payload():
    client = TestClient(create_app())
    response = client.post(
        "/v1/route-policy-agent/evaluate",
        json={
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
            "field_outputs": [
                {
                    "field_name": "invoice_no",
                    "status": "resolved",
                    "value": "INV-001",
                }
            ],
            "refs_with_text": [
                {
                    "field_name": "invoice_no",
                    "refs": [
                        {
                            "document_id": "doc-1",
                            "text": "发票号码：INV-001",
                        }
                    ],
                }
            ],
            "field_processes": [
                {
                    "field_name": "invoice_no",
                    "broad_extraction": {
                        "search_queries": ["发票号 OR 发票号码"],
                    },
                    "field_resolution": {
                        "final_decision_used": True,
                    },
                }
            ],
            "policy_options": {
                "max_refs_per_field": 1,
                "max_ref_text_chars": 10,
            },
        },
    )

    assert response.status_code == 422
    assert "policy_options" in response.text


def test_route_policy_agent_route_returns_422_for_business_validation_error(monkeypatch):
    from service.route_policy_agent import processor as processor_module

    def fake_evaluate(**kwargs):
        del kwargs
        raise ValueError("unknown field_output.field_name: unknown")

    monkeypatch.setattr(processor_module, "evaluate", fake_evaluate)

    client = TestClient(create_app())
    response = client.post(
        "/v1/route-policy-agent/evaluate",
        json={
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
            "field_outputs": [
                {
                    "field_name": "unknown",
                    "status": "resolved",
                    "value": "INV-001",
                }
            ],
            "refs_with_text": [
                {
                    "field_name": "unknown",
                    "refs": [
                        {
                            "document_id": "doc-1",
                            "text": "发票号码：INV-001",
                        }
                    ],
                }
            ],
            "field_processes": [
                {
                    "field_name": "unknown",
                    "broad_extraction": {
                        "search_queries": ["发票号 OR 发票号码"],
                    },
                    "field_resolution": {
                        "final_decision_used": True,
                    },
                }
            ],
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "unknown field_output.field_name: unknown"
