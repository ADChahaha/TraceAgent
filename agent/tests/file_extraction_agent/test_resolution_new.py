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
    assert (
        '<table-ref id="dp-table-1" label="通知" rows="1" columns="姓名 | 学院" />'
        in outline
    )
    assert outline.endswith("\n</outline>")
    assert "正文不应出现在 overview" not in outline
    assert "{'id':" not in outline


def test_resolution_messages_embed_compact_document_outline():
    messages = build_resolution_messages(_state())
    content = "\n\n".join(message.content for message in messages)

    assert "Document outline" in content
    assert '<table-ref id="dp-table-1" label="通知" rows="1" columns="姓名 | 学院" />' in content
    assert "Document overview:" not in content
    assert "{'tree':" not in content
    assert "You are the field-writing agent" in content
    assert "Each field must be finalized exactly once with set_field" in content
    assert "Write reasons in the same language as the document whenever possible" in content
    assert "There is no broad plan" in content
    assert "Use the task field descriptions and document outline as the primary guide" in content
    assert "Do not wait for or call update_plan" in content
    assert "Broad plan" not in content
    assert "update_plan(plan_index" not in content
    assert "Once evidence for a field is sufficient, the next related tool call must be set_field" in content
    assert "Prefer checking contents/index pages first" in content
    assert "Use search_elements" in content
    assert "Search results include readable HTML and observed evidence ids" in content
    assert "use those evidence_ids directly in set_field" in content
    assert "Only call read_element when the search match is ambiguous" in content
    assert "Use scan_document(scope_id, query, reason, limit) only after choosing a scope id" in content
    assert "scan_document is an isolated no-tool reader" in content
    assert "scans all content under that one scope id" in content
    assert "If read_section hits the section size limit, it automatically uses the isolated reader on that same section id" in content
    assert "use the returned read_section candidates directly when they are sufficient" in content
    assert "It returns candidate block evidence only" in content
    assert "Search results are candidates only" not in content
    assert "depth=2 reads nearby subsections" in content
    assert "If you have used read_element more than 3 times in the same section for one field" in content
    assert "All SQL column names must be wrapped in double quotes" in content
    assert "query_audit few-shot" in content
    assert "Blank filter columns must be interpreted with table context" in content
    assert "Do not claim blank rows are normal merely because WHERE did not select them" in content
    assert "neighboring columns, captions, headers, or group titles" in content
    assert "set_field evidence_ids must come from this run's search_elements/scan_document/read_element/read_section/table_extraction/paragraph_extraction results" in content
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


def test_resolution_nudge_counts_search_results_as_observed_evidence():
    state = _state()
    state.actions = [
        {"tool_name": "search_elements"},
        {"tool_name": "search_elements"},
        {"tool_name": "read_element"},
        {"tool_name": "search_elements"},
    ]

    instruction = _continue_instruction(state)

    assert "Stop browsing broadly" in instruction
    assert "the next tool call must be set_field" in instruction


def test_resolution_graph_does_not_expose_update_plan_tool():
    state = _state()
    tools = build_tools(state)
    tool_names = [getattr(tool, "name", getattr(tool, "__name__", "")) for tool in tools]

    assert "update_plan" not in tool_names
    assert tool_names[0] == "search_elements"
    assert "scan_document" in tool_names
