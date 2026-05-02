from __future__ import annotations

from service.file_extraction_agent.impl.broad_new import BroadPlan
from service.file_extraction_agent.impl.html_state import build_graph_state
from service.file_extraction_agent.impl.html_tools import build_tools
from service.file_extraction_agent.impl.resolution_new import (
    build_resolution_messages,
    build_resolution_graph,
    format_document_outline,
)
from service.file_extraction_agent.input_adapter import build_graph_input
from langchain_core.messages import AIMessage


def _state():
    html = """
    <h2 id="dp-h2-1">通知</h2>
    <p id="dp-p-1">正文不应出现在 overview</p>
    <table id="dp-table-1">
      <tr id="dp-tr-1"><th>姓名</th><th>学院</th></tr>
      <tr id="dp-tr-2"><td>张三</td><td>计算机学院</td></tr>
    </table>
    """
    state = build_graph_state(
        build_graph_input(
            html=html,
            task_spec={"fields": [{"name": "student_name", "type": "string", "required": True}]},
        )
    )
    state.broad_plan = BroadPlan(summary="名单", plan=["读取表格"], risks=[])
    return state


def test_format_document_outline_returns_compact_text_not_raw_json():
    outline = format_document_outline(_state().document.tree)

    assert outline.startswith("<outline>\n")
    assert '<section id="dp-h2-1" level="1" title="通知">' in outline
    assert (
        '<table-ref id="dp-table-1" name="通知" rows="1" columns="姓名 | 学院" />'
        in outline
    )
    assert outline.endswith("\n</outline>")
    assert "正文不应出现在 overview" not in outline
    assert "{'id':" not in outline


def test_resolution_messages_embed_compact_document_outline():
    messages = build_resolution_messages(_state())
    content = "\n\n".join(message.content for message in messages)

    assert "Document outline:" in content
    assert '<table-ref id="dp-table-1" name="通知" rows="1" columns="姓名 | 学院" />' in content
    assert "Document overview:" not in content
    assert "{'tree':" not in content
    assert "you are a field-writing agent" in content
    assert "call set_field exactly once" in content
    assert "prefer read_section" in content
    assert "Do not collect all evidence first" in content
    assert "Do not issue a large batch of read_element calls" in content
    assert "current field's immediate evidence" in content


def test_resolution_graph_nudges_model_when_it_stops_before_finish():
    state = _state()
    state.field_states["student_name"] = {
        "name": "student_name",
        "status": "resolved",
        "value": "张三",
        "evidence_ids": ["dp-tr-2"],
        "failure_reason": None,
    }
    calls = []

    class FakeBoundModel:
        def invoke(self, messages):
            calls.append(messages)
            if len(calls) == 1:
                return AIMessage(content="I found the answer but stopped.")
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "finish",
                        "args": {},
                        "id": "finish-call",
                    }
                ],
            )

    class FakeModel:
        def bind_tools(self, tools):
            return FakeBoundModel()

    graph = build_resolution_graph(FakeModel(), build_tools(state), state)
    graph.invoke({"messages": build_resolution_messages(state)}, config={"recursion_limit": 8})

    assert len(calls) >= 2
    assert "All fields have been set" in calls[1][-1].content
    assert state.actions[-1]["tool_name"] == "finish"
