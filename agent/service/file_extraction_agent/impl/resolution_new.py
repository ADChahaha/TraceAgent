"""Resolution agent loop for HTML extraction."""

from __future__ import annotations

from html import escape
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import MessagesState
from langgraph.prebuilt import ToolNode

from service.file_extraction_agent.impl.html_tools import build_tools


def build_resolution_messages(state: Any) -> list[Any]:
    system = SystemMessage(
        content=(
            "You are the resolution agent in an HTML document extraction workflow. "
            "Your actions will be replayed in the frontend as a human-like document search animation, "
            "so every tool call must be clear, credible, and displayable. "
            "You are not a chat assistant or a research assistant. You are the field-writing agent. "
            "Your goal is to finish every field in Task fields, but the reading path should look like a document review. "
            "Each field must be finalized exactly once with set_field, with status resolved or failed. "
            "Handle one field at a time, or one tightly related group of fields. "
            "Do not browse many unrelated areas and then write all fields at the end. "
            "The action trace must support frontend replay: "
            "Use reading stage tools to maintain append-only human-readable execution stages. "
            "Do not create a stage for the initial overview; the compact outline is already in this prompt. "
            "Stages are not field checklists, and they should not copy field names, labels, questions, or hypotheses as titles. "
            "Start a stage only when entering a useful document-understanding phase, then append progress when reading changes the stage state. "
            "Stage obligations: "
            "Reading phase: use overview/read/query/preview tools to gather evidence; do not call set_field or review_stage_evidence. "
            "Conclude checkpoint: call conclude only after you have finished reading enough evidence and are ready to write fields; do not use conclude as a vague progress summary. "
            "Writing phase: use review_stage_evidence if helpful, then set_field with stage_id and rationale; do not read while conclude is still the latest progress. "
            "Premature conclude correction: only if conclude turns out to lack enough evidence, append investigate/compare/verify_absence to the same stage before any more reading; this withdraws the write-ready checkpoint. "
            "Complete phase: call complete_stage only when this document-understanding goal is stable and you are ready to move to a materially different goal. "
            "Use investigate, compare, or verify_absence while reading. "
            "When the current stage has enough evidence for one or more field decisions, append progress type conclude before writing fields. "
            "After conclude, reading tools are disabled while conclude remains the latest progress: review notes and set fields if evidence is sufficient. "
            "Do not use conclude as a normal continuation point; only correct a premature conclude by appending investigate/compare/verify_absence to the same stage before reading more. "
            "Use compare only when a decision depends on relationships between observed evidence, not for ordinary task-field matching. "
            "Do not use compare for ordinary task-field matching; write that reasoning in set_field rationale. "
            "Use verify_absence before absence-like field outcomes when the checked scope matters. "
            "Complete the current stage before starting another stage; only one stage can be in progress at a time. "
            "Use record_stage_evidence for important reusable candidate evidence, after precise inline/table-row/list-item evidence has been observed. "
            "Candidate evidence notes and fields share the same evidence_ids, so do not create or pass separate note ids when writing fields. "
            "Use review_stage_evidence only when it helps you remember earlier stage evidence; it is optional and returns notes in recorded order. "
            "set_field and review_stage_evidence are allowed only after the current stage's latest progress is conclude. "
            "set_field must include a field-level rationale. "
            "Use task fields to understand what evidence is needed; write stages as document-understanding goals. "
            "1. Pick the next unresolved evidence need or related field group, inspect the outline, and choose the narrowest useful read action. "
            "2. Read only the evidence needed to complete that stage; record important candidate evidence when helpful. "
            "3. Append conclude before writing fields from that stage. "
            "4. After conclude, set fields with stage_id and rationale; if evidence is insufficient, append investigate to the same stage to withdraw the write-ready checkpoint, then read more and conclude again. "
            "5. After all fields are done, call finish. "
            "Use preview_inline_evidence before set_field when final text evidence is still a whole text block. "
            "set_field evidence_ids for resolved fields must be precise: text values need inline ids, tables need row ids, "
            "and lists need item ids. "
            "Use the built-in document outline to choose section ids. Call overview first when the outline is not enough. "
            "Document outline may include section containers and block items in document order. "
            "Use the bound tool descriptions as the source of truth for exact arguments and reading behavior. "
            "Do not wander around cover pages or unrelated headings unless the current field needs the document title. "
            "All SQL column names must be wrapped in double quotes. "
            "query_table returns rows, table_audit, and summary; these are table observations, not risk conclusions. "
            "rows[].values show the selected SQL cells directly, including blank selected cells as empty strings. "
            "table_audit.blank_cells gives whole-table blank counts and the first blank row ids for each affected column. "
            "Explain query_table summary and table_audit only when they affect the current field. "
            "If selected rows are empty, selected cells are blank, or table_audit suggests the table structure is unreliable for the field, "
            "continue querying, use a safer query, or set_field(status='failed') to request human review. "
            "If a tool returns ok=false or error, do not quit. Read the error, fix parameters, and retry. "
            "set_field evidence_ids must come from this run's read_blocks/read_block_range/read_list/query_table/preview_inline_evidence results. "
            "Do not write fields using only the overview."
        )
    )
    human = HumanMessage(
        content="\n\n".join(
            [
                "Task fields (each field must be set_field):\n" + _task_fields_text(state.task_spec),
                "Document outline（用于选择 overview/read_section/read_blocks/read_block_range/read_list/query_table，并在文本读取后用 preview_inline_evidence 细化证据）:\n"
                + format_document_outline(state.document.tree),
            ]
        )
    )
    return [system, human]


def run_resolution(state: Any, resolution_model: Any) -> dict[str, Any]:
    tools = build_tools(state)
    messages = build_resolution_messages(state)

    if _supports_bind_tools(resolution_model):
        graph = build_resolution_graph(resolution_model, tools, state)
        output = graph.invoke({"messages": messages}, config={"recursion_limit": state.run_options.max_tool_calls * 2 + 10})
        finish_actions = [
            action for action in state.actions if action.get("tool_name") == "finish"
        ]
        if finish_actions:
            return finish_actions[-1]["result"]
        return {"ok": False, "errors": [{"message": "resolution did not call finish"}], "output": output}

    return _run_fake_model_loop(state, resolution_model)


def build_resolution_graph(resolution_model: Any, tools: list[Any], state: Any):
    model = resolution_model.bind_tools(tools)
    tool_node = ToolNode(tools)

    def call_model(graph_state: MessagesState):
        return {"messages": [model.invoke(graph_state["messages"])]}

    def nudge_model(graph_state: MessagesState):
        return {"messages": [HumanMessage(content=_continue_instruction(state))]}

    def should_continue(graph_state: MessagesState):
        if len(state.actions) >= state.run_options.max_tool_calls:
            return END
        if _has_successful_finish(state):
            return END
        messages = graph_state["messages"]
        last_message = messages[-1]
        if getattr(last_message, "tool_calls", None):
            return "tools"
        if _should_force_set_field_nudge(state):
            return "nudge"
        if not _has_successful_finish(state) and _should_nudge_resolution(state):
            return "nudge"
        return END

    graph = StateGraph(MessagesState)
    graph.add_node("agent", call_model)
    graph.add_node("tools", tool_node)
    graph.add_node("nudge", nudge_model)
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", should_continue, {"tools": "tools", "nudge": "nudge", END: END})
    graph.add_edge("tools", "agent")
    graph.add_edge("nudge", "agent")
    return graph.compile()


def _run_fake_model_loop(state: Any, model: Any) -> dict[str, Any]:
    """Small deterministic loop for unit tests using models that emit tool calls."""

    tools = {getattr(tool, "name", getattr(tool, "__name__", "")): tool for tool in build_tools(state)}
    messages = build_resolution_messages(state)
    for _ in range(state.run_options.max_tool_calls):
        call = model.invoke(messages)
        name = _read(call, "tool_name") or _read(call, "name")
        args = _read(call, "arguments", {}) or _read(call, "args", {}) or {}
        tool = tools.get(name)
        if tool is None:
            return {"ok": False, "errors": [{"message": f"unknown tool: {name}"}]}
        result = tool.invoke(args) if hasattr(tool, "invoke") else tool(**args)
        messages.append({"tool": name, "result": result})
        if name == "finish":
            return result
    return {"ok": False, "errors": [{"message": "max_tool_calls exceeded"}]}


def _supports_bind_tools(model: Any) -> bool:
    return callable(getattr(model, "bind_tools", None))


def _has_successful_finish(state: Any) -> bool:
    return any(
        action.get("tool_name") == "finish" and (action.get("result") or {}).get("ok") is True
        for action in getattr(state, "actions", []) or []
    )


def _has_unfinished_fields(state: Any) -> bool:
    field_states = getattr(state, "field_states", {}) or {}
    return any(field.name not in field_states for field in getattr(state.task_spec, "fields", []) or [])


def _should_nudge_resolution(state: Any) -> bool:
    return bool(getattr(state.task_spec, "fields", []) or [])


def _continue_instruction(state: Any) -> str:
    field_states = getattr(state, "field_states", {}) or {}
    if _should_force_set_field_nudge(state):
        return (
            "You have read several pieces of evidence but have not written a field. Stop browsing broadly. "
            "If evidence for the current field is sufficient, append conclude for the current stage, then call set_field with stage_id and rationale. "
            "If evidence is still insufficient, do not write or read directly; append investigate to the same stage to withdraw the write-ready checkpoint, then continue reading. "
            "Do not switch to another field. "
            "Do not answer in plain text."
        )
    missing = [
        field.name
        for field in getattr(state.task_spec, "fields", []) or []
        if field.name not in field_states
    ]
    if missing:
        return (
            "Extraction is not complete. Missing fields: "
            + ", ".join(missing)
            + ". Continue using tools. Use missing fields only to identify unresolved evidence needs. "
            "Do not turn the missing field list into stages. "
            "Read only necessary evidence for the next unresolved evidence need or related field group, append conclude when that stage has enough evidence, "
            "then call set_field with stage_id and rationale. "
            "Do not collect evidence for many fields and write them all later. Do not answer in plain text."
        )
    return (
        "All fields have been set_field, but finish has not succeeded yet. Call finish now. "
        "If finish returns errors, fix them with set_field and call finish again. Do not answer in plain text."
    )


def _task_fields_text(task_spec: Any) -> str:
    lines = []
    for field in getattr(task_spec, "fields", []) or []:
        lines.append(
            f"- {field.name}: type={field.type}, required={field.required}, description={field.description or ''}"
            + _enum_variants_text(field)
        )
    if getattr(task_spec, "instructions", None):
        lines.append("Instructions: " + task_spec.instructions)
    return "\n".join(lines)


def _enum_variants_text(field: Any) -> str:
    if _read(field, "type") != "enum":
        return ""
    variants = _read(field, "variants", []) or []
    parts = [
        f"{_read(variant, 'name')}:{_read(variant, 'type')}"
        for variant in variants
    ]
    return (
        ", variants="
        + " | ".join(parts)
        + '. Use enum values as tagged objects: {"variant": "name", "value": ...}'
    )


def format_document_outline(tree: list[dict[str, Any]]) -> str:
    lines: list[str] = ["<outline>"]
    index_nodes = select_index_outline_nodes(tree)
    if index_nodes:
        lines.append('  <index-pages purpose="use these first to locate sections">')
        _append_outline_lines(index_nodes, lines, depth=2, section_stack=[])
        lines.append("  </index-pages>")
        lines.append('  <main-outline purpose="use after choosing candidate sections from index pages">')
        _append_outline_lines(tree, lines, depth=2, section_stack=[], skip_ids={node.get("id", "") for node in index_nodes})
        lines.append("  </main-outline>")
    else:
        _append_outline_lines(tree, lines, depth=1, section_stack=[])
    lines.append("</outline>")
    return "\n".join(lines)


def select_index_outline_nodes(tree: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return likely table-of-contents/index nodes for the model to consult first."""

    selected: list[dict[str, Any]] = []
    for node in tree:
        text = str(node.get("text") or node.get("label") or "")
        normalized = text.replace(" ", "").lower()
        if (
            "目次" in normalized
            or "contents" in normalized
            or "tableofcontents" in normalized
            or "index" == normalized
        ):
            selected.append(node)
    return selected[:2]


def _append_outline_lines(
    nodes: list[dict[str, Any]],
    lines: list[str],
    depth: int,
    section_stack: list[str],
    skip_ids: set[str] | None = None,
) -> None:
    for node in nodes:
        if skip_ids and node.get("id", "") in skip_ids:
            continue
        indent = "  " * depth
        node_id = node.get("id", "")
        node_type = node.get("type", "")
        if node_type == "TABLE":
            columns = " | ".join(str(column) for column in node.get("columns", []) or [])
            row_count = node.get("row_count", 0)
            label = node.get("label") or (section_stack[-1] if section_stack else "")
            label_attr = f' label="{_attr(label)}"' if label else ""
            lines.append(
                f'{indent}<table-ref id="{_attr(node_id)}"{label_attr} rows="{_attr(row_count)}" columns="{_attr(columns)}" />'
            )
            continue

        if node_type in {"TITLE", "SECTION_HEADER"}:
            text = str(node.get("text", ""))
            level = _heading_level(node_type, depth)
            lines.append(
                f'{indent}<section id="{_attr(node_id)}" level="{_attr(level)}" title="{_attr(text)}">'
            )
            _append_outline_lines(
                node.get("children", []) or [],
                lines,
                depth + 1,
                [*section_stack, text],
                skip_ids=skip_ids,
            )
            lines.append(f"{indent}</section>")
        else:
            _append_outline_lines(
                node.get("children", []) or [],
                lines,
                depth,
                section_stack,
                skip_ids=skip_ids,
            )


def _should_force_set_field_nudge(state: Any) -> bool:
    actions = getattr(state, "actions", []) or []
    if len(actions) < 4:
        return False
    recent = actions[-4:]
    if any(action.get("tool_name") == "set_field" for action in recent):
        return False
    read_like = {"read_section", "read_blocks", "read_block_range", "read_list", "query_table", "preview_inline_evidence"}
    return sum(1 for action in recent if action.get("tool_name") in read_like) >= 4


def _heading_level(node_type: str, depth: int) -> int:
    if node_type == "TITLE":
        return 1
    return max(1, depth)


def _attr(value: Any) -> str:
    return escape(str(value), quote=True)


def _read(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


__all__ = [
    "build_resolution_messages",
    "build_resolution_graph",
    "format_document_outline",
    "run_resolution",
]
