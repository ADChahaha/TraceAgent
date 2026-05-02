from __future__ import annotations

from types import SimpleNamespace

from service.file_extraction_agent.impl.broad_new import BroadPlan
from service.file_extraction_agent.impl.graph import build_failed_result, map_state_to_result, run_extraction_graph
from service.file_extraction_agent.impl.html_state import build_graph_state
from service.file_extraction_agent.input_adapter import build_graph_input


class FakeBroadModel:
    def bind_tools(self, tools, tool_choice=None):
        return self

    def invoke(self, messages):
        return SimpleNamespace(
            tool_calls=[
                {
                    "name": "return_broad_plan",
                    "args": {
                        "summary": "名单",
                        "plan": ["query table", "set field", "finish"],
                        "risks": [],
                    },
                }
            ]
        )


class FakeResolutionModel:
    def __init__(self):
        self.calls = [
            {
                "tool_name": "table_extraction",
                "arguments": {
                    "table_id": "dp-table-1",
                    "sql": "SELECT 姓名 FROM data WHERE 学院 = '计算机学院'",
                },
            },
            {
                "tool_name": "read_element",
                "arguments": {"element_id": "dp-tr-2"},
            },
            {
                "tool_name": "set_field",
                "arguments": {
                    "name": "student_name",
                    "value": "张三",
                    "evidence_ids": ["dp-table-1", "dp-tr-2"],
                },
            },
            {"tool_name": "finish", "arguments": {}},
        ]

    def invoke(self, messages):
        return self.calls.pop(0)


def _input():
    html = """
    <h2 id="dp-h2-1">通知</h2>
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


def test_run_extraction_graph_executes_broad_then_resolution():
    result = run_extraction_graph(
        extraction_input=_input(),
        broad_model=FakeBroadModel(),
        resolution_model=FakeResolutionModel(),
    )

    assert result.status == "completed"
    assert result.result["student_name"] == "张三"
    assert len(result.trace["actions"]) >= 1
