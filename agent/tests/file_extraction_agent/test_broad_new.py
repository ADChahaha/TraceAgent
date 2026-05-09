from __future__ import annotations

from types import SimpleNamespace

from service.file_extraction_agent.impl.broad_new import build_broad_messages, parse_broad_plan_tool_call, run_broad_planner


def test_build_broad_messages_includes_task_and_tree():
    state = SimpleNamespace(
        task_spec=SimpleNamespace(fields=[SimpleNamespace(name="student_name", type="string")]),
        document=SimpleNamespace(tree=[{"id": "dp-h2-1", "type": "SECTION_HEADER", "text": "通知"}]),
        extraction_input=SimpleNamespace(html='<p id="dp-p-1">全文正文</p>'),
    )

    messages = build_broad_messages(state)
    content = "\n".join(message["content"] for message in messages)

    assert "student_name" in content
    assert "dp-h2-1" in content
    assert '<p id="dp-p-1">全文正文</p>' in content
    assert "resolution agent" in content
    assert "Tools available to the resolution agent" in content
    assert "Exact tool arguments and reading behavior come from the resolution agent's bound tool docstrings" in content
    assert "overview, read_section, read_blocks, read_block_range, read_list, query_table, set_field, finish" in content
    assert "You must not call these tools in the broad stage" in content
    assert "Do not plan an unbounded SELECT * for large tables" in content
    assert "Small tables may use SELECT *" in content
    assert "SELECT * FROM data LIMIT 50 OFFSET 0" in content
    assert "only call return_broad_plan" in content
    assert "must not extract final field values directly" in content
    assert "field=value" in content
    assert "The plan is a navigation plan, not an answer draft" in content
    assert "Do not include concrete extracted values" in content
    assert "Do not write concrete extracted values or normalized field values" in content
    assert "Use the field names and descriptions from task_spec as categories" in content
    assert "effective_date" not in content
    assert "jurisdiction" not in content
    assert "term/survival/confidentiality" not in content
    assert "marked with update_plan" in content
    assert "p004_b002" not in content
    assert "enrollment-count" not in content
    assert "Japanese Criteria" not in content
    assert "master program" not in content
    assert "Do not prefill answers" in content
    assert "set_field reason should explain query_audit.summary" in content
    assert "Do not turn blank filter columns directly into a risk conclusion" in content
    assert "Write plan text in the same language as the document whenever possible" in content


def test_run_broad_planner_skips_model_and_returns_default_plan():
    captured = {}

    class FakeBroadModel:
        def bind_tools(self, tools, tool_choice=None):
            captured["tool_names"] = [getattr(tool, "name", "") for tool in tools]
            captured["tool_choice"] = tool_choice
            return self

        def invoke(self, messages):
            raise AssertionError("broad model should not be invoked in no-plan mode")

    state = SimpleNamespace(
        task_spec=SimpleNamespace(fields=[SimpleNamespace(name="student_name", type="string")]),
        document=SimpleNamespace(tree=[]),
    )

    plan = run_broad_planner(state, FakeBroadModel())

    assert captured == {}
    assert plan.summary == "Default document navigation plan"
    assert plan.plan == [
        "Review the document overview and identify relevant sections.",
        "Read needed section block previews and then read exact blocks, lists, or tables.",
        "Write each field with observed evidence and finish the run.",
    ]
    assert plan.risks == []
    assert state.broad_plan == plan


def test_parse_broad_plan_tool_call_reads_function_arguments():
    message = SimpleNamespace(
        tool_calls=[
            {
                "name": "return_broad_plan",
                "args": {
                    "summary": "名单文档",
                    "plan": ["overview", "query table", "set fields"],
                    "risks": ["表头可能跨页"],
                },
            }
        ]
    )

    plan = parse_broad_plan_tool_call(message)

    assert plan.summary == "名单文档"
    assert plan.plan == ["overview", "query table", "set fields"]
    assert plan.risks == ["表头可能跨页"]


def test_parse_broad_plan_keeps_string_list_values_as_single_items():
    message = SimpleNamespace(
        tool_calls=[
            {
                "name": "return_broad_plan",
                "args": {
                    "summary": "s",
                    "plan": "read relevant tables",
                    "risks": '["multi program document", "split tables"]',
                },
            }
        ]
    )

    plan = parse_broad_plan_tool_call(message)

    assert plan.plan == ["read relevant tables"]
    assert plan.risks == ["multi program document", "split tables"]
