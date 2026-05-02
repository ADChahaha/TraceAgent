"""Resolution agent loop for HTML extraction."""

from __future__ import annotations

from html import escape
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import MessagesState
from langgraph.prebuilt import ToolNode

from service.file_extraction_agent.impl.broad_new import format_broad_plan
from service.file_extraction_agent.impl.html_tools import build_tools


def build_resolution_messages(state: Any) -> list[Any]:
    system = SystemMessage(
        content=(
            "You are the resolution agent for an HTML document extraction task. "
            "You are not a research assistant; you are a field-writing agent. "
            "Your goal is to write every field in Task fields. For every field, "
            "you must eventually call set_field exactly once with status "
            "'resolved' or 'failed'. Use the built-in document outline to choose "
            "element ids. When an outline candidate is a section heading, prefer "
            "read_section with the smallest useful depth instead of repeatedly "
            "reading the heading element. Inspect specific elements with "
            "read_element, query tables with table_extraction, and search text "
            "with paragraph_extraction. As soon as you have enough evidence for one "
            "field, immediately call set_field for that field before reading "
            "more unrelated elements. Do not collect all evidence first. Do not "
            "scan the whole document before writing fields. Do not issue a large "
            "batch of read_element calls just to explore. Even though tool calls "
            "may be available in parallel, use them only for the current field's "
            "immediate evidence, then stop reading and call set_field. Work in "
            "this loop: choose one field, inspect only the elements needed for "
            "that field, call set_field for that field, move to the next field, "
            "then call finish after all fields are set. If finish returns "
            "ok=false, fix the listed fields and call finish again. "
            "When writing SQL for table_extraction, always wrap every column name "
            "in double quotes. If a tool returns ok=false or an error, inspect the "
            "error and retry with corrected arguments instead of stopping. "
            "You must not call set_field with evidence ids that have not first "
            "appeared in a read_element, table_extraction, or paragraph_extraction "
            "tool result in this run."
        )
    )
    human = HumanMessage(
        content="\n\n".join(
            [
                "Broad plan:\n" + format_broad_plan(state.broad_plan),
                "Task fields:\n" + _task_fields_text(state.task_spec),
                "Document outline:\n" + format_document_outline(state.document.tree),
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
    missing = [
        field.name
        for field in getattr(state.task_spec, "fields", []) or []
        if field.name not in field_states
    ]
    if missing:
        return (
            "You stopped before completing the extraction. Missing fields: "
            + ", ".join(missing)
            + ". Continue with tool calls. For each missing field, inspect only the necessary evidence, "
            "call set_field exactly once, and then call finish. Do not answer in plain text."
        )
    return (
        "All fields have been set, but finish has not succeeded yet. Call finish now. "
        "If finish returns errors, fix them with set_field and call finish again. Do not answer in plain text."
    )


def _task_fields_text(task_spec: Any) -> str:
    lines = []
    for field in getattr(task_spec, "fields", []) or []:
        lines.append(
            f"- {field.name}: type={field.type}, required={field.required}, description={field.description or ''}"
        )
    if getattr(task_spec, "instructions", None):
        lines.append("Instructions: " + task_spec.instructions)
    return "\n".join(lines)


def format_document_outline(tree: list[dict[str, Any]]) -> str:
    lines: list[str] = ["<outline>"]
    _append_outline_lines(tree, lines, depth=1, section_stack=[])
    lines.append("</outline>")
    return "\n".join(lines)


def _append_outline_lines(
    nodes: list[dict[str, Any]],
    lines: list[str],
    depth: int,
    section_stack: list[str],
) -> None:
    for node in nodes:
        indent = "  " * depth
        node_id = node.get("id", "")
        node_type = node.get("type", "")
        if node_type == "TABLE":
            columns = " | ".join(str(column) for column in node.get("columns", []) or [])
            table_name = node.get("table_name") or (section_stack[-1] if section_stack else "unnamed")
            row_count = node.get("row_count", 0)
            lines.append(
                f'{indent}<table-ref id="{_attr(node_id)}" name="{_attr(table_name)}" rows="{_attr(row_count)}" columns="{_attr(columns)}" />'
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
            )
            lines.append(f"{indent}</section>")
        else:
            _append_outline_lines(
                node.get("children", []) or [],
                lines,
                depth,
                section_stack,
            )


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
