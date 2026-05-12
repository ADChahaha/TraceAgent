from __future__ import annotations

from types import SimpleNamespace

from service.file_extraction_agent.impl.broad_new import BroadPlan
from service.file_extraction_agent.impl.graph import build_failed_result, map_state_to_result, run_extraction_graph
from service.file_extraction_agent.impl.html_state import build_graph_state
from service.file_extraction_agent.input_adapter import build_graph_input


class FakeBroadModel:
    def bind_tools(self, tools, tool_choice=None):
        raise AssertionError("broad model should not be bound in no-plan mode")

    def invoke(self, messages):
        raise AssertionError("broad model should not be invoked in no-plan mode")


class FakeResolutionModel:
    def __init__(self):
        self.calls = [
            {
                "tool_name": "update_plan",
                "arguments": {
                    "plan_index": 1,
                    "status": "in_progress",
                    "reason": "开始读取名单表",
                },
            },
            {
                "tool_name": "read_blocks",
                "arguments": {
                    "section_id": "dp-table-1",
                    "indexes": [0],
                    "reason": "先确认名单表的列名",
                },
            },
            {
                "tool_name": "query_table",
                "arguments": {
                    "section_id": "dp-table-1",
                    "block_offset": 0,
                    "sql": "SELECT \"姓名\" FROM data WHERE \"学院\" = '计算机学院'",
                    "reason": "查询计算机学院对应的姓名行",
                },
            },
            {
                "tool_name": "set_field",
                "arguments": {
                    "name": "student_name",
                    "value": "张三",
                    "evidence_ids": ["dp-table-1", "dp-tr-2"],
                    "reason": "dp-table-1 和 dp-tr-2 支持学生姓名为张三",
                },
            },
            {"tool_name": "finish", "arguments": {}},
        ]

    def invoke(self, messages):
        return self.calls.pop(0)


class FakeResolutionModelWithScan:
    def __init__(self):
        self.calls = [
            {
                "tool_name": "read_blocks",
                "arguments": {
                    "section_id": "dp-p-1",
                    "indexes": [0],
                    "reason": "读取姓名字段候选证据",
                },
            },
            {
                "tool_name": "preview_inline_evidence",
                "arguments": {
                    "source_id": "dp-p-1",
                    "start_index": 0,
                    "count": 5,
                    "reason": "把姓名段落细化为字段证据",
                },
            },
            {
                "tool_name": "set_field",
                "arguments": {
                    "name": "student_name",
                    "value": "张三",
                    "evidence_ids": ["dp-p-1::inline-0"],
                    "reason": "dp-p-1::inline-0 支持学生姓名为张三",
                },
            },
            {"tool_name": "finish", "arguments": {}},
        ]

    def invoke(self, messages):
        return self.calls.pop(0)


class FakeDocumentScanModel:
    def __init__(self):
        self.invoked = False

    def bind_tools(self, tools, tool_choice=None):
        raise AssertionError("document scan model must not receive tools")

    def invoke(self, messages):
        self.invoked = True
        return {
            "content": '{"candidates": [{"element_id": "dp-p-1", "reason": "姓名段落"}]}'
        }


def _input():
    html = """
    <h2 id="dp-h2-1">通知</h2>
    <p id="dp-p-1">学生姓名：张三</p>
    <table id="dp-table-1">
      <tr id="dp-tr-1"><th>姓名</th><th>学院</th></tr>
      <tr id="dp-tr-2"><td>张三</td><td>计算机学院</td></tr>
    </table>
    """
    return build_graph_input(
        html=html,
        task_spec={"fields": [{"name": "student_name", "type": "string", "required": True}]},
    )


def test_map_state_to_result_returns_completed_payload():
    state = build_graph_state(_input())
    state.broad_plan = BroadPlan(summary="Extract", plan=["Extract"], risks=[])
    state.field_states["student_name"] = {
        "name": "student_name",
        "status": "resolved",
        "value": "张三",
        "evidence_ids": ["dp-table-1", "dp-tr-2"],
    }

    result = map_state_to_result(state)

    assert result.status == "completed"
    assert result.result["student_name"] == "张三"
    assert result.trace["broad_plan"]["summary"] == "Extract"


def test_build_failed_result_preserves_trace():
    state = build_graph_state(_input())

    result = build_failed_result(state=state, stage="broad", exc=RuntimeError("boom"))

    assert result.status == "failed"
    assert result.failure_reason == "boom"
    assert result.trace["failed_stage"] == "broad"


def test_run_extraction_graph_skips_broad_plan_then_runs_resolution():
    result = run_extraction_graph(
        extraction_input=_input(),
        broad_model=FakeBroadModel(),
        resolution_model=FakeResolutionModel(),
    )

    assert result.status == "completed"
    assert result.result["student_name"] == "张三"
    assert result.trace["broad_plan"] is None
    assert len(result.trace["actions"]) >= 1


def test_run_extraction_graph_runs_new_read_tools_without_document_scan_model():
    scan_model = FakeDocumentScanModel()

    result = run_extraction_graph(
        extraction_input=_input(),
        broad_model=scan_model,
        resolution_model=FakeResolutionModelWithScan(),
    )

    assert result.status == "completed"
    assert result.result["student_name"] == "张三"
    assert scan_model.invoked is False
    assert [action["tool_name"] for action in result.trace["actions"]] == [
        "read_blocks",
        "preview_inline_evidence",
        "set_field",
        "finish",
    ]
