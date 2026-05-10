from __future__ import annotations

from service.file_extraction_agent.impl.html_state import build_graph_state
from service.file_extraction_agent.impl.html_tools import build_tools
from service.file_extraction_agent.impl.resolution_new import (
    build_resolution_messages,
    build_resolution_graph,
    format_document_outline,
    select_index_outline_nodes,
    _continue_instruction,
    _task_fields_text,
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
    assert "Use reading stage tools to maintain append-only human-readable execution stages" in content
    assert "Do not create a stage for the initial overview" in content
    assert "Stages are not field checklists" in content
    assert "A stage is a related evidence-to-field writing unit" in content
    assert "Only write multiple fields in one stage when they share the same section, table, list, or comparison chain" in content
    assert "If the next field needs a materially different clause, section, table, list, or hypothesis, complete the current stage and start another stage" in content
    assert "Complete the current stage before starting another stage" in content
    assert "Stage obligations:" in content
    assert "Stage startup: after start_stage, append investigate/compare/verify_absence before any reading tool" in content
    assert "Reading phase: after a reading progress exists, use overview/read/query/preview tools" in content
    assert "Conclude checkpoint: call conclude only after you have finished reading enough evidence and are ready to write fields" in content
    assert "conclude cannot be the first progress event in a stage" in content
    assert "Writing phase: use review_stage_evidence if helpful, then set_field" in content
    assert "Premature conclude correction: only if conclude turns out to lack enough evidence" in content
    assert "this withdraws the write-ready checkpoint" in content
    assert "Complete phase: call complete_stage only when this document-understanding goal is stable" in content
    assert "When the current stage has enough evidence for one or more field decisions, append progress type conclude before writing fields" in content
    assert "After conclude, reading tools are disabled while conclude remains the latest progress" in content
    assert "Do not use conclude as a normal continuation point" in content
    assert "only correct a premature conclude by appending investigate/compare/verify_absence to the same stage before reading more" in content
    assert "Use compare only when a decision depends on relationships between observed evidence" in content
    assert "Use verify_absence for absence-like or null outcomes when the checked scope matters" in content
    assert "not a mandatory per-field checklist" in content
    assert "Do not use compare for ordinary task-field matching" in content
    assert "record_stage_evidence" in content
    assert "set_field and review_stage_evidence are allowed only after the current stage's latest progress is conclude" in content
    assert "set_field must include a field-level rationale" in content
    assert "refocus" not in content.lower()
    assert "issue progress" not in content.lower()
    assert "Evidence note ids" not in content
    assert "evidence_note_ids" not in content
    assert "update_soft_plan" not in content
    assert "soft plan" not in content.lower()
    assert "Pick the next unresolved evidence need or related field group" in content
    assert "Append conclude before writing fields from that stage" in content
    assert "append investigate to the same stage to withdraw the write-ready checkpoint" in content
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
    assert "Every tool call except finish requires a reason" not in content
    assert "Write reasons in the same language as the document whenever possible" not in content


def test_resolution_task_fields_include_enum_variants_for_tagged_values():
    state = build_graph_state(
        build_graph_input(
            html='<p id="dp-p-1">正文</p>',
            task_spec={
                "fields": [
                    {
                        "name": "answer",
                        "type": "enum",
                        "required": True,
                        "variants": [
                            {"name": "text", "type": "string"},
                            {"name": "scores", "type": "list[number]"},
                            {"name": "missing", "type": "null"},
                        ],
                    }
                ]
            },
        )
    )

    fields_text = _task_fields_text(state.task_spec)

    assert "answer: type=enum" in fields_text
    assert "variants=text:string | scores:list[number] | missing:null" in fields_text
    assert "Use enum values as tagged objects" in fields_text


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

    assert "Stop browsing broadly" in instruction
    assert "append conclude for the current stage" in instruction
    assert "append investigate/compare/verify_absence before reading" in instruction
    assert "then call set_field with stage_id and rationale" in instruction
    assert "If evidence is still insufficient" in instruction
    assert "do not write or read directly" in instruction
    assert "append investigate to the same stage to withdraw the write-ready checkpoint" in instruction
    assert "then append conclude and set_field" not in instruction


def test_resolution_nudge_keeps_missing_fields_from_becoming_plan_items():
    instruction = _continue_instruction(_state())

    assert "Use missing fields only to identify unresolved evidence needs" in instruction
    assert "Do not turn the missing field list into stages" in instruction
    assert "After start_stage, append investigate/compare/verify_absence before reading" in instruction
    assert "append conclude only after reading progress and enough evidence" in instruction
    assert "For each missing field" not in instruction


def test_resolution_graph_exposes_plan_reading_stage_and_read_tools():
    state = _state()
    tools = build_tools(state)
    tool_names = [getattr(tool, "name", getattr(tool, "__name__", "")) for tool in tools]

    assert tool_names == [
        "start_stage",
        "append_stage_progress",
        "record_stage_evidence",
        "review_stage_evidence",
        "complete_stage",
        "overview",
        "read_section",
        "read_blocks",
        "read_block_range",
        "read_list",
        "query_table",
        "preview_inline_evidence",
        "set_field",
        "finish",
    ]


def test_resolution_tools_do_not_expose_reason_argument():
    tools = build_tools(_state())

    for tool in tools:
        name = getattr(tool, "name", getattr(tool, "__name__", ""))
        schema = getattr(tool, "args_schema", None)
        if schema is None:
            continue
        fields = getattr(schema, "model_fields", {})
        assert "reason" not in fields, name
