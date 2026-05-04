from __future__ import annotations

import json

from service.file_extraction_agent.schemas import FieldDefinition, TaskSpec
from service.route_policy_agent import processor as processor_module
from service.route_policy_agent.schemas import (
    EvidenceTextRef,
    FieldRefsWithText,
    RouteFieldProcess,
    RouteFieldOutput,
    RouteProcessStage,
)


class FakePolicyClient:
    def __init__(self, decisions: list[dict[str, str]]):
        self.decisions = decisions
        self.calls: list[dict[str, object]] = []

    def invoke(self, *, output_schema, messages):
        self.calls.append({"output_schema": output_schema, "messages": messages})
        return output_schema.model_validate(self.decisions.pop(0))


def _task_spec(*, critical: bool = False, required: bool = True) -> TaskSpec:
    return TaskSpec(
        task_name="invoice",
        fields=[
            FieldDefinition(
                field_name="invoice_no",
                display_name="发票号",
                type="string",
                required=required,
                critical=critical,
            )
        ],
    )


def _two_field_task_spec() -> TaskSpec:
    return TaskSpec(
        task_name="invoice",
        fields=[
            FieldDefinition(
                field_name="invoice_no",
                display_name="发票号",
                type="string",
                required=True,
            ),
            FieldDefinition(
                field_name="due_date",
                display_name="付款期限",
                type="string",
                required=True,
            ),
        ],
    )


def _refs_group(ref_text: str = "发票号码：INV-001") -> list[FieldRefsWithText]:
    return [
        FieldRefsWithText(
            field_name="invoice_no",
            refs=[
                EvidenceTextRef(
                    document_id="doc-1",
                    page=1,
                    block_id="b1",
                    text=ref_text,
                )
            ],
        )
    ]


def _field_processes() -> list[RouteFieldProcess]:
    return [
        RouteFieldProcess(
            field_name="invoice_no",
            broad_extraction=RouteProcessStage(
                search_queries=["发票号 OR 发票号码"],
                candidate_action_count=1,
                finish_reason="候选足够，结束 broad",
            ),
            field_resolution=RouteProcessStage(
                search_queries=[],
                final_decision_used=True,
                reason="候选证据支持字段值",
            ),
        )
    ]


def test_evaluate_accepts_resolved_field_when_policy_client_accepts():
    fake_client = FakePolicyClient(
        decisions=[
            {
                "route": "accept",
                "route_reason": "字段值和 refs 文本一致，可自动放行",
            }
        ]
    )

    result = processor_module.evaluate(
        task_spec=_task_spec(),
        field_outputs=[
            RouteFieldOutput(
                field_name="invoice_no",
                status="resolved",
                value="INV-001",
            )
        ],
        refs_with_text=_refs_group(),
        field_processes=_field_processes(),
        policy_client=fake_client,
    )

    assert result.status == "completed"
    assert result.field_routes[0].route == "accept"
    assert result.field_routes[0].needs_review is False
    assert fake_client.calls[0]["output_schema"].__name__ == "RoutePolicyDecision"
    user_payload = json.loads(fake_client.calls[0]["messages"][1]["content"])
    assert user_payload["field_output"]["value"] == "INV-001"
    assert user_payload["refs_with_text"][0]["text"] == "发票号码：INV-001"
    assert user_payload["field_process"]["broad_extraction"]["search_queries"] == [
        "发票号 OR 发票号码"
    ]
    assert user_payload["field_process"]["broad_extraction"]["counted_fields"] == []
    assert "tool_results" not in json.dumps(user_payload, ensure_ascii=False)


def test_evaluate_keeps_complete_refs_with_text_in_policy_prompt():
    fake_client = FakePolicyClient(
        decisions=[
            {
                "route": "accept",
                "route_reason": "全部证据文本都进入 prompt 后可判断字段可信",
            }
        ]
    )
    long_ref_text = (
        "发票号码：INV-001\n"
        + "这是一段用于确认 route policy prompt 不截断的长证据文本。" * 80
        + "\n完整尾部-不要截断"
    )
    refs = [
        EvidenceTextRef(
            document_id="doc-1",
            page=index + 1,
            block_id=f"b{index + 1}",
            text=long_ref_text if index == 0 else f"证据第 {index + 1} 条",
        )
        for index in range(55)
    ]

    processor_module.evaluate(
        task_spec=_task_spec(),
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
                refs=refs,
            )
        ],
        field_processes=_field_processes(),
        policy_client=fake_client,
    )

    user_payload = json.loads(fake_client.calls[0]["messages"][1]["content"])
    assert len(user_payload["refs_with_text"]) == 55
    assert user_payload["refs_with_text"][0]["text"] == long_ref_text
    assert user_payload["refs_with_text"][0]["text"].endswith("完整尾部-不要截断")
    assert user_payload["refs_with_text"][-1]["text"] == "证据第 55 条"


def test_evaluate_includes_source_field_process_for_derived_count_field():
    fake_client = FakePolicyClient(
        decisions=[
            {
                "route": "accept",
                "route_reason": "数量字段由来源字段候选数量支持",
            },
            {
                "route": "accept",
                "route_reason": "列表字段证据充分",
            },
        ]
    )
    task_spec = TaskSpec(
        task_name="academic_papers",
        fields=[
            FieldDefinition(
                field_name="academic_paper_count",
                display_name="学术论文数量",
                type="string",
                required=True,
                validation_rules={
                    "source_field": "academic_paper_names",
                    "operation": "count_items",
                },
            ),
            FieldDefinition(
                field_name="academic_paper_names",
                display_name="学术论文名称",
                type="list",
                required=True,
            ),
        ],
    )

    processor_module.evaluate(
        task_spec=task_spec,
        field_outputs=[
            RouteFieldOutput(
                field_name="academic_paper_count",
                status="resolved",
                value="13",
            ),
            RouteFieldOutput(
                field_name="academic_paper_names",
                status="resolved",
                value=["论文 A"],
            ),
        ],
        refs_with_text=[
            FieldRefsWithText(
                field_name="academic_paper_count",
                refs=[
                    EvidenceTextRef(
                        document_id="doc-1",
                        page=1,
                        block_id="b1",
                        text="| 1 | 学术论文 | 论文 A |",
                    )
                ],
            ),
            FieldRefsWithText(
                field_name="academic_paper_names",
                refs=[
                    EvidenceTextRef(
                        document_id="doc-1",
                        page=1,
                        block_id="b1",
                        text="| 1 | 学术论文 | 论文 A |",
                    )
                ],
            ),
        ],
        field_processes=[
            RouteFieldProcess(
                field_name="academic_paper_count",
                broad_extraction=RouteProcessStage(
                    candidate_action_count=1,
                    finish_reason="复制来源字段候选后结束 broad",
                ),
                field_resolution=RouteProcessStage(
                    final_decision_used=True,
                    reason="来源字段最终列表共 13 项",
                ),
            ),
            RouteFieldProcess(
                field_name="academic_paper_names",
                broad_extraction=RouteProcessStage(
                    search_queries=["学术论文 OR 论文题目 OR 作品类型"],
                    candidate_action_count=13,
                    finish_reason="候选足够，结束 broad",
                ),
                field_resolution=RouteProcessStage(
                    final_decision_used=True,
                    reason="候选证据支持列表字段",
                ),
            ),
        ],
        policy_client=fake_client,
    )

    user_payload = json.loads(fake_client.calls[0]["messages"][1]["content"])
    system_prompt = fake_client.calls[0]["messages"][0]["content"]
    assert "related_field_processes" in system_prompt
    assert "来源字段" in system_prompt
    assert user_payload["field_output"]["field_name"] == "academic_paper_count"
    assert user_payload["field_process"]["broad_extraction"]["search_queries"] == []
    assert user_payload["related_field_processes"][0]["field_name"] == "academic_paper_names"
    assert user_payload["related_field_processes"][0]["broad_extraction"]["search_queries"] == [
        "学术论文 OR 论文题目 OR 作品类型"
    ]
    assert "tool_results" not in json.dumps(user_payload, ensure_ascii=False)


def test_evaluate_marks_resolved_field_for_review_when_evidence_is_insufficient():
    fake_client = FakePolicyClient(
        decisions=[
            {
                "route": "review",
                "route_reason": "refs 只说明订单号，不能支持发票号字段值",
            }
        ]
    )

    result = processor_module.evaluate(
        task_spec=_task_spec(),
        field_outputs=[
            RouteFieldOutput(
                field_name="invoice_no",
                status="resolved",
                value="INV-001",
            )
        ],
        refs_with_text=_refs_group(ref_text="订单号：ORDER-9"),
        field_processes=_field_processes(),
        policy_client=fake_client,
    )

    assert result.field_routes[0].route == "review"
    assert result.field_routes[0].needs_review is True
    assert "不能支持" in result.field_routes[0].route_reason


def test_evaluate_reviews_resolved_field_with_no_extraction_process_without_model_call():
    fake_client = FakePolicyClient(decisions=[])

    result = processor_module.evaluate(
        task_spec=_task_spec(),
        field_outputs=[
            RouteFieldOutput(
                field_name="invoice_no",
                status="resolved",
                value="INV-001",
            )
        ],
        refs_with_text=_refs_group(),
        field_processes=[
            RouteFieldProcess(
                field_name="invoice_no",
                broad_extraction=RouteProcessStage(),
                field_resolution=RouteProcessStage(status="resolved"),
            )
        ],
        policy_client=fake_client,
    )

    assert result.field_routes[0].route == "review"
    assert result.field_routes[0].needs_review is True
    assert "抽取过程摘要为空" in result.field_routes[0].route_reason
    assert fake_client.calls == []


def test_evaluate_passes_query_audit_and_reason_to_policy_prompt():
    fake_client = FakePolicyClient(
        decisions=[
            {
                "route": "accept",
                "route_reason": "模型已说明空白分类列表示普通寝室，字段值和证据一致。",
            }
        ]
    )
    process = RouteFieldProcess(
        field_name="invoice_no",
        broad_extraction=RouteProcessStage(
            search_queries=["发票号 OR 发票号码"],
            candidate_action_count=1,
            finish_reason="候选足够，结束 broad",
            diagnostics=[
                {
                    "source": "table_extraction",
                    "table_id": "p002_b001",
                    "query": "SELECT \"房间\" FROM data WHERE \"模范/文明\" = '文明寝室'",
                    "quality_type": "query_audit",
                    "summary": "返回 12 行；筛选列“模范/文明”空白 149 行；输出列“房间”无空值。",
                }
            ],
        ),
        field_resolution=RouteProcessStage(
            final_decision_used=True,
            reason="使用“模范/文明 = 文明寝室”筛出 12 行；该列空白行表示未获评普通寝室，不应计入；选中行的“房间”列无空值。",
        ),
    )

    result = processor_module.evaluate(
        task_spec=_task_spec(),
        field_outputs=[
            RouteFieldOutput(
                field_name="invoice_no",
                status="resolved",
                value="INV-001",
            )
        ],
        refs_with_text=_refs_group(),
        field_processes=[process],
        policy_client=fake_client,
    )

    assert result.field_routes[0].route == "accept"
    assert len(fake_client.calls) == 1
    user_payload = json.loads(fake_client.calls[0]["messages"][1]["content"])
    diagnostics = user_payload["field_process"]["broad_extraction"]["diagnostics"]
    assert diagnostics[0]["quality_type"] == "query_audit"
    assert "status" not in diagnostics[0]
    assert "空白 149 行" in diagnostics[0]["summary"]
    assert "空白行表示未获评普通寝室" in user_payload["field_process"]["field_resolution"]["reason"]
    system_prompt = fake_client.calls[0]["messages"][0]["content"]
    assert "Few-shot examples for query_audit" in system_prompt
    assert "空白筛选列必须结合表格上下文判断" in system_prompt
    assert "不能只因为空白行未被 WHERE 选中就说正常" in system_prompt
    assert "相邻列、表注或表头" in system_prompt
    assert "非空分布" not in system_prompt


def test_evaluate_passes_table_audit_summary_to_policy_prompt():
    fake_client = FakePolicyClient(
        decisions=[
            {
                "route": "accept",
                "route_reason": "表格整体有空 cell，但当前字段 refs 和查询结果充分",
            }
        ]
    )
    process = RouteFieldProcess(
        field_name="invoice_no",
        broad_extraction=RouteProcessStage(
            search_queries=["发票号 OR 发票号码"],
            candidate_action_count=1,
            finish_reason="候选足够，结束 broad",
            diagnostics=[
                {
                    "source": "table_extraction",
                    "table_id": "p002_b001",
                    "quality_type": "table_audit",
                    "summary": "表格 14 行；3 列；空白单元格：作品类型 空白 1 行。",
                }
            ],
        ),
        field_resolution=RouteProcessStage(
            final_decision_used=True,
            reason="候选证据支持字段值",
        ),
    )

    result = processor_module.evaluate(
        task_spec=_task_spec(),
        field_outputs=[
            RouteFieldOutput(
                field_name="invoice_no",
                status="resolved",
                value="INV-001",
            )
        ],
        refs_with_text=_refs_group(),
        field_processes=[process],
        policy_client=fake_client,
    )

    assert result.field_routes[0].route == "accept"
    assert len(fake_client.calls) == 1
    user_payload = json.loads(fake_client.calls[0]["messages"][1]["content"])
    diagnostics = user_payload["field_process"]["broad_extraction"]["diagnostics"]
    assert diagnostics[0]["quality_type"] == "table_audit"
    assert diagnostics[0]["summary"] == "表格 14 行；3 列；空白单元格：作品类型 空白 1 行。"
    assert "status" not in diagnostics[0]


def test_evaluate_reviews_failed_required_field_without_model_call():
    fake_client = FakePolicyClient(decisions=[])

    result = processor_module.evaluate(
        task_spec=_task_spec(critical=True, required=True),
        field_outputs=[
            RouteFieldOutput(
                field_name="invoice_no",
                status="failed",
            )
        ],
        refs_with_text=[
            FieldRefsWithText(
                field_name="invoice_no",
                refs=[],
            )
        ],
        field_processes=_field_processes(),
        policy_client=fake_client,
    )

    assert result.field_routes[0].route == "review"
    assert result.field_routes[0].needs_review is True
    assert "required" in result.field_routes[0].route_reason
    assert fake_client.calls == []


def test_evaluate_reviews_missing_required_field_output_without_model_call():
    fake_client = FakePolicyClient(
        decisions=[
            {
                "route": "accept",
                "route_reason": "发票号证据充分",
            }
        ]
    )

    result = processor_module.evaluate(
        task_spec=_two_field_task_spec(),
        field_outputs=[
            RouteFieldOutput(
                field_name="invoice_no",
                status="resolved",
                value="INV-001",
            )
        ],
        refs_with_text=_refs_group(),
        field_processes=_field_processes(),
        policy_client=fake_client,
    )

    routes_by_name = {route.field_name: route for route in result.field_routes}
    assert routes_by_name["invoice_no"].route == "accept"
    assert routes_by_name["due_date"].route == "review"
    assert routes_by_name["due_date"].needs_review is True
    assert "required" in routes_by_name["due_date"].route_reason
    assert "没有返回该字段" in routes_by_name["due_date"].route_reason
    assert len(fake_client.calls) == 1


def test_evaluate_reviews_empty_required_field_value_without_model_call():
    fake_client = FakePolicyClient(decisions=[])

    result = processor_module.evaluate(
        task_spec=_task_spec(required=True),
        field_outputs=[
            RouteFieldOutput(
                field_name="invoice_no",
                status="resolved",
                value="",
            )
        ],
        refs_with_text=_refs_group(ref_text="发票号码为空"),
        field_processes=_field_processes(),
        policy_client=fake_client,
    )

    assert result.field_routes[0].route == "review"
    assert result.field_routes[0].needs_review is True
    assert "required" in result.field_routes[0].route_reason
    assert "字段值为空" in result.field_routes[0].route_reason
    assert fake_client.calls == []


def test_evaluate_builds_policy_client_when_not_provided(monkeypatch):
    seen_builder_call: dict[str, object] = {}
    fake_client = FakePolicyClient(
        decisions=[
            {
                "route": "accept",
                "route_reason": "证据充分",
            }
        ]
    )

    def fake_build_policy_client(*, base_url, api_key, model, structured_output_strategy):
        seen_builder_call["base_url"] = base_url
        seen_builder_call["api_key"] = api_key
        seen_builder_call["model"] = model
        seen_builder_call["structured_output_strategy"] = structured_output_strategy
        return fake_client

    monkeypatch.setattr(processor_module, "build_policy_client", fake_build_policy_client)

    processor_module.evaluate(
        task_spec=_task_spec(),
        field_outputs=[
            RouteFieldOutput(
                field_name="invoice_no",
                status="resolved",
                value="INV-001",
            )
        ],
        refs_with_text=_refs_group(),
        field_processes=_field_processes(),
        base_url="https://llm.example.com/v1",
        openai_api_key="test-key",
        model="small-route-model",
        structured_output_strategy="tool_call",
    )

    assert seen_builder_call == {
        "base_url": "https://llm.example.com/v1",
        "api_key": "test-key",
        "model": "small-route-model",
        "structured_output_strategy": "tool_call",
    }
