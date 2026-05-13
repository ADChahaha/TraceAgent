from __future__ import annotations

from service.file_extraction_agent.impl.html_state import build_graph_state
from service.file_extraction_agent.impl.html_tools import build_tools
from service.file_extraction_agent.impl.resolution_new import (
    build_resolution_messages,
    build_resolution_graph,
    format_document_outline,
    select_index_outline_nodes,
    _continue_instruction,
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
    return state


def test_format_document_outline_returns_compact_text_not_raw_json():
    outline = format_document_outline(_state().document.tree)

    assert outline.startswith("<outline>\n")
    assert '<section id="dp-h2-1" level="1" title="通知">' in outline
    assert '<table-ref id="dp-table-1" rows="1" columns="姓名 | 学院" />' in outline
    assert outline.endswith("\n</outline>")
    assert "正文不应出现在 overview" not in outline
    assert "{'id':" not in outline


def test_resolution_messages_embed_compact_document_outline():
    messages = build_resolution_messages(_state())
    content = "\n\n".join(message.content for message in messages)

    assert "Document outline" in content
    assert '<table-ref id="dp-table-1" rows="1" columns="姓名 | 学院" />' in content
    assert "Document overview:" not in content
    assert "{'tree':" not in content
    assert "You are the field-writing agent" in content
    assert "Each field must be finalized exactly once with set_field" in content
    assert "Write reasons in the same language as the document whenever possible" in content
    assert "Use update_soft_plan(plan) as a soft local work log" in content
    assert "Use the task field descriptions and document outline as the primary guide" in content
    assert "Each plan item should read like a compact stage title" in content
    assert "which related field group may be resolved" in content
    assert "Start by using update_soft_plan to group fields by likely evidence topic" in content
    assert "Group fields of the same kind or fields that share part of the same evidence" in content
    assert "can be judged together" in content
    assert "If a plan item mentions task fields, write each field name separately exactly as it appears in Task fields" in content
    assert "Do not use ranges, through, all fields, remaining fields, or similar shorthand" in content
    assert "Do not mention task-specific field families such as choice/status plus evidence" not in content
    assert "same entity, event, condition, amount, date, table row, or evidence source" not in content
    assert "Update that same plan item from in_progress to completed after the related fields are set" in content
    assert "Treat each soft-plan item as a local work unit" in content
    assert "Before moving to a materially different topic, clause area, or field group, refresh update_soft_plan" in content
    assert "prefer evidence observed or previewed after the latest update_soft_plan" in content
    assert "reread or preview that evidence again in the current plan" in content
    assert "These plan rules are soft guidance for memory and replay clarity" in content
    assert "After previewing or querying final evidence, call record_note" in content
    assert "record_note is a replay memory aid and does not replace set_field" in content
    assert "broad-plan" not in content
    assert "broad plan" not in content.lower()
    assert "Null is a normal resolved value for fields or enum variants whose declared type is null" in content
    assert "Do not use status failed just because the value is null" in content
    assert "Use status failed only when the field cannot be completed reliably and needs human review" in content
    assert "Once evidence for a field is sufficient, the next related tool call must be set_field" in content
    assert "Call overview first when the outline is not enough" in content
    assert "Document outline may include section containers and block items in document order" in content
    assert "Use the bound tool descriptions as the source of truth for exact arguments and reading behavior" in content
    assert "All SQL column names must be wrapped in double quotes" in content
    assert "query_table returns rows, table_audit, and summary" in content
    assert "Explain query_table summary and table_audit only when they affect the current field" in content
    assert "query_audit.summary" not in content
    assert "query_audit few-shot" not in content
    assert "Example 1" not in content
    assert "Example 2" not in content
    assert "\"category\"='target'" not in content
    assert "Use preview_inline_evidence before set_field when final text evidence is still a whole text block" in content
    assert "set_field evidence_ids for resolved fields must be precise" in content
    assert "text values need inline ids" in content
    assert "tables need row ids" in content
    assert "lists need item ids" in content
    assert "非空分布" not in content


def test_format_document_outline_prioritizes_index_pages():
    tree = [
        {"id": "cover", "type": "TITLE", "text": "表紙", "children": []},
        {
            "id": "toc",
            "type": "TITLE",
            "text": "目 次",
            "children": [
                {"id": "toc-item", "type": "SECTION_HEADER", "text": "Ⅰ．出願資格", "children": []}
            ],
        },
        {
            "id": "main",
            "type": "SECTION_HEADER",
            "text": "Ⅰ．出願資格",
            "children": [],
        },
    ]

    outline = format_document_outline(tree)

    assert '<index-pages purpose="use these first to locate sections">' in outline
    assert '<main-outline purpose="use after choosing candidate sections from index pages">' in outline
    assert outline.index('id="toc"') < outline.index('id="cover"')
    assert outline.count('id="toc"') == 1
    assert select_index_outline_nodes(tree)[0]["id"] == "toc"


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
    assert "All fields have been set_field" in calls[1][-1].content
    assert state.actions[-1]["tool_name"] == "finish"


def test_resolution_nudge_counts_new_read_tools_as_observed_evidence():
    state = _state()
    state.actions = [
        {"tool_name": "read_section"},
        {"tool_name": "read_blocks"},
        {"tool_name": "read_block_range"},
        {"tool_name": "preview_inline_evidence"},
    ]

    instruction = _continue_instruction(state)

    assert "Stop browsing across unrelated areas" in instruction
    assert "the next tool call must be set_field" in instruction


def test_resolution_graph_exposes_plan_and_new_read_tools():
    state = _state()
    tools = build_tools(state)
    tool_names = [getattr(tool, "name", getattr(tool, "__name__", "")) for tool in tools]

    assert tool_names == [
        "update_soft_plan",
        "overview",
        "read_section",
        "read_blocks",
        "read_block_range",
        "read_list",
        "query_table",
        "preview_inline_evidence",
        "record_note",
        "set_field",
        "finish",
    ]
