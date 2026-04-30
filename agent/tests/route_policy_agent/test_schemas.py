from __future__ import annotations

from pydantic import ValidationError

from service.file_extraction_agent.schemas import FieldDefinition, TaskSpec
from service.route_policy_agent.schemas import (
    FieldRefsWithText,
    RouteFieldProcess,
    RouteFieldOutput,
    RouteProcessStage,
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
            field_processes=[
                RouteFieldProcess(
                    field_name="invoice_no",
                    broad_extraction=RouteProcessStage(search_queries=["发票号 OR 发票号码"]),
                    field_resolution=RouteProcessStage(final_decision_used=True),
                )
            ],
            trace={"fields": []},
        )
    except ValidationError as exc:
        assert "trace" in str(exc)
    else:
        raise AssertionError("route policy 输入不应接收 extraction trace")


def test_route_policy_input_accepts_list_field_output():
    route_input = RoutePolicyInput(
        task_spec=TaskSpec(
            task_name="academic_paper_extraction",
            fields=[
                FieldDefinition(
                    field_name="academic_paper_titles",
                    display_name="学术论文名称",
                    type="list",
                    required=True,
                )
            ],
        ),
        field_outputs=[
            RouteFieldOutput(
                field_name="academic_paper_titles",
                status="resolved",
                value=["论文 A", "论文 B"],
            )
        ],
        refs_with_text=[
            FieldRefsWithText(
                field_name="academic_paper_titles",
                refs=[],
            )
        ],
        field_processes=[
            RouteFieldProcess(
                field_name="academic_paper_titles",
                broad_extraction=RouteProcessStage(
                    search_queries=["学术论文 OR 论文题目 OR 作品类型"],
                    candidate_action_count=2,
                    counted_fields=[
                        {"field_name": "academic_paper_titles", "count": 2}
                    ],
                    finish_reason="候选足够，结束 broad",
                ),
                field_resolution=RouteProcessStage(
                    search_queries=["学术论文 OR SCI OR 论文替代"],
                    final_decision_used=True,
                    reason="候选证据支持字段值",
                ),
            )
        ],
    )

    assert route_input.task_spec.fields[0].type == "list"
    assert route_input.field_outputs[0].value == ["论文 A", "论文 B"]
    assert route_input.field_processes[0].broad_extraction.search_queries == [
        "学术论文 OR 论文题目 OR 作品类型"
    ]
    assert route_input.field_processes[0].broad_extraction.counted_fields[0].count == 2
    assert route_input.policy_options.max_refs_per_field == 50


def test_route_policy_input_rejects_tool_result_in_field_processes():
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
            field_processes=[
                {
                    "field_name": "invoice_no",
                    "broad_extraction": {
                        "search_queries": ["发票号 OR 发票号码"],
                        "tool_results": [{"text": "发票号码：INV-001"}],
                    },
                    "field_resolution": {
                        "final_decision_used": True,
                    },
                }
            ],
        )
    except ValidationError as exc:
        assert "tool_results" in str(exc)
    else:
        raise AssertionError("route policy 过程摘要不应接收工具返回结果")


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
