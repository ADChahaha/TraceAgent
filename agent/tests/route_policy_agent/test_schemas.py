from __future__ import annotations

from pydantic import ValidationError

from service.file_extraction_agent.schemas import FieldDefinition, TaskSpec
from service.route_policy_agent.schemas import (
    FieldRefsWithText,
    RouteFieldOutput,
    RoutePolicyDecision,
    RoutePolicyInput,
)


def test_route_policy_input_rejects_extraction_trace_payload():
    try:
        RoutePolicyInput(
            task_spec=TaskSpec(
                task_name="invoice",
                fields=[
                    FieldDefinition(
                        field_name="invoice_no",
                        display_name="发票号",
                        type="string",
                    )
                ],
            ),
            field_outputs=[
                RouteFieldOutput(
                    field_name="invoice_no",
                    status="resolved",
                    value="INV-001",
                )
            ],
            refs_with_text=[
                FieldRefsWithText(
                    field_name="invoice_no",
                    refs=[],
                )
            ],
            trace={"fields": []},
        )
    except ValidationError as exc:
        assert "trace" in str(exc)
    else:
        raise AssertionError("route policy 输入不应接收 extraction trace")


def test_route_policy_decision_rejects_new_field_value_payload():
    try:
        RoutePolicyDecision(
            route="review",
            route_reason="证据支持原值不足，需要人工检查",
            suggested_value="INV-002",
        )
    except ValidationError as exc:
        assert "suggested_value" in str(exc)
    else:
        raise AssertionError("route policy 模型输出不允许给出新的字段值")
