from __future__ import annotations

from service.file_extraction_agent.impl.graph import build_failed_result, map_state_to_result, run_extraction_graph
from service.file_extraction_agent.impl.html_state import build_graph_state
from service.file_extraction_agent.input_adapter import build_graph_input


class FakeResolutionModel:
    def __init__(self):
        self.calls = [
            {
                "tool_name": "start_stage",
                "arguments": {
                    "title": "理解名单来源",
                    "focus": "查看名单表并确认学生姓名来源",
                    "basis": "学生姓名可能来自名单表，表格列名可先确认。",
                },
            },
            {
                "tool_name": "append_stage_progress",
                "arguments": {
                    "stage_id": "stage-1",
                    "type": "investigate",
                    "summary": "准备读取名单表并查询学生姓名行。",
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
                "tool_name": "record_stage_evidence",
                "arguments": {
                    "stage_id": "stage-1",
                    "field_name": "student_name",
                    "evidence_ids": ["dp-table-1", "dp-tr-2"],
                    "observation": "名单表中计算机学院对应的姓名是张三。",
                },
            },
            {
                "tool_name": "complete_stage",
                "arguments": {
                    "stage_id": "stage-1",
                    "finding": "名单表行证据已经足以写学生姓名字段。",
                    "fields": [
                        {
                            "name": "student_name",
                            "value": "张三",
                            "evidence_ids": ["dp-table-1", "dp-tr-2"],
                            "status": "resolved",
                            "rationale": "查询到的表格行直接覆盖学生姓名。",
                        }
                    ],
                },
            },
            {"tool_name": "finish", "arguments": {"confirm": "finish"}},
        ]

    def invoke(self, messages):
        return self.calls.pop(0)


class FakeResolutionModelWithScan:
    def __init__(self):
        self.calls = [
            {
                "tool_name": "start_stage",
                "arguments": {
                    "title": "理解姓名段落",
                    "focus": "读取姓名段落并细化 inline 证据",
                    "basis": "姓名字段可能直接来自通知正文。",
                },
            },
            {
                "tool_name": "append_stage_progress",
                "arguments": {
                    "stage_id": "stage-1",
                    "type": "investigate",
                    "summary": "准备读取姓名段落并细化 inline 证据。",
                },
            },
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
                "tool_name": "record_stage_evidence",
                "arguments": {
                    "stage_id": "stage-1",
                    "field_name": "student_name",
                    "evidence_ids": ["dp-p-1::inline-0"],
                    "observation": "姓名段落直接写明学生姓名是张三。",
                },
            },
            {
                "tool_name": "complete_stage",
                "arguments": {
                    "stage_id": "stage-1",
                    "finding": "姓名段落 inline 证据已经足以写字段。",
                    "fields": [
                        {
                            "name": "student_name",
                            "value": "张三",
                            "evidence_ids": ["dp-p-1::inline-0"],
                            "status": "resolved",
                            "rationale": "inline 证据直接覆盖学生姓名。",
                        }
                    ],
                },
            },
            {"tool_name": "finish", "arguments": {"confirm": "finish"}},
        ]

    def invoke(self, messages):
        return self.calls.pop(0)


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
    state.reading_stages = [
        {
            "stage_id": "stage-1",
            "title": "检查名单表",
            "focus": "确认学生姓名来源",
            "basis": "姓名字段可能来自名单表。",
            "status": "completed",
            "progress": [],
            "evidence_notes": [],
            "finding": "表格给出姓名。",
        }
    ]
    state.field_states["student_name"] = {
        "name": "student_name",
        "status": "resolved",
        "value": "张三",
        "evidence_ids": ["dp-table-1", "dp-tr-2"],
    }

    result = map_state_to_result(state)

    assert result.status == "completed"
    assert result.result["student_name"] == "张三"
    assert result.trace["reading_stages"][0]["title"] == "检查名单表"
    assert "broad_plan" not in result.trace
    assert "plan_statuses" not in result.trace
    assert "soft_plan" not in result.trace


def test_build_failed_result_preserves_trace():
    state = build_graph_state(_input())

    result = build_failed_result(state=state, stage="resolution", exc=RuntimeError("boom"))

    assert result.status == "failed"
    assert result.failure_reason == "boom"
    assert result.trace["failed_stage"] == "resolution"


def test_run_extraction_graph_runs_resolution_without_broad_stage():
    result = run_extraction_graph(
        extraction_input=_input(),
        resolution_model=FakeResolutionModel(),
    )

    assert result.status == "completed"
    assert result.result["student_name"] == "张三"
    assert [action["tool_name"] for action in result.trace["actions"]] == [
        "start_stage",
        "append_stage_progress",
        "read_blocks",
        "query_table",
        "record_stage_evidence",
        "complete_stage",
        "finish",
    ]
    assert result.trace["reading_stages"][0]["title"] == "理解名单来源"


def test_run_extraction_graph_runs_new_read_tools_without_document_scan_model():
    result = run_extraction_graph(
        extraction_input=_input(),
        resolution_model=FakeResolutionModelWithScan(),
    )

    assert result.status == "completed"
    assert result.result["student_name"] == "张三"
    assert [action["tool_name"] for action in result.trace["actions"]] == [
        "start_stage",
        "append_stage_progress",
        "read_blocks",
        "preview_inline_evidence",
        "record_stage_evidence",
        "complete_stage",
        "finish",
    ]
