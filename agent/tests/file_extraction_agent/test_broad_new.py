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
    assert "Available resolution tools" not in content
    assert "只能 return_broad_plan" in content
    assert "不能直接抽取最终字段值" in content
    assert "field=value" in content
    assert "用 update_plan 标记" in content
    assert "读取 p004_b002 表格" in content
    assert "不能预先填答案" in content


def test_run_broad_planner_binds_only_plan_output_function():
    captured = {}

    class FakeBroadModel:
        def bind_tools(self, tools, tool_choice=None):
            captured["tool_names"] = [getattr(tool, "name", "") for tool in tools]
            captured["tool_choice"] = tool_choice
            return self

        def invoke(self, messages):
            return SimpleNamespace(
                tool_calls=[
                    {
                        "name": "return_broad_plan",
                        "args": {"summary": "s", "plan": ["p"], "risks": []},
                    }
                ]
            )

    state = SimpleNamespace(
        task_spec=SimpleNamespace(fields=[SimpleNamespace(name="student_name", type="string")]),
        document=SimpleNamespace(tree=[]),
    )

    run_broad_planner(state, FakeBroadModel())

    assert captured["tool_names"] == ["return_broad_plan"]
    assert captured["tool_choice"] == "return_broad_plan"


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
