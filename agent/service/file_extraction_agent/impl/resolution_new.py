"""Resolution loop for virtual-tree file extraction."""

from __future__ import annotations

from typing import Any, Iterable

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import MessagesState
from langgraph.prebuilt import ToolNode

from service.file_extraction_agent.impl.html_tools import build_tools


def build_resolution_messages(state: Any) -> list[Any]:
    system = SystemMessage(
        content=(
            "You are the field extraction agent for a semantic HTML virtual file tree. "
            "Use only tool calls; do not answer in plain text. "
            "Available tools are tree(path, depth, reason), read(path, offset, limit, reason), "
            "anchors(path, reason), query_table(path, sql, offset, limit, reason), "
            "write_field(field_id, value, evidence, status, reason), and submit_result(reason). "
            "Every reason is a user-visible action explanation, not hidden reasoning and not evidence. "
            "Use tree to navigate documents and sections. Use read to inspect .md/.list/.table files. "
            "Use anchors only for paragraph .md files to get Sxxx sentence ids. "
            "Lists expose Ixxx item ids in read output. Tables expose Rxxx row ids in read and query_table output. "
            "Use evidence selectors: {path, sentences}, {path, items}, or {path, rows}. "
            "Write each schema field with write_field when the value is supported or mark it missing when the document does not mention it. "
            "Once you have enough evidence for a field, call write_field for that field before continuing to unrelated fields. "
            "Call submit_result after all fields have been written. If submit_result returns errors, fix fields and submit again."
        )
    )
    human = HumanMessage(
        content="\n\n".join(
            [
                "Task fields:\n" + _task_fields_text(state.task_spec),
                "Initial virtual tree:\n" + state.document.tree_text("/", depth=2),
            ]
        )
    )
    return [system, human]


def run_resolution(state: Any, resolution_model: Any) -> dict[str, Any]:
    outcome: dict[str, Any] = {"ok": False, "errors": [{"message": "resolution did not run"}]}
    for outcome in run_resolution_stream(state, resolution_model):
        pass
    return outcome


def run_resolution_stream(state: Any, resolution_model: Any) -> Iterable[dict[str, Any]]:
    tools = build_tools(state)
    messages = build_resolution_messages(state)
    if _supports_bind_tools(resolution_model):
        graph = build_resolution_graph(resolution_model, tools, state)
        output = None
        for output in graph.stream(
            {"messages": messages},
            config={"recursion_limit": state.run_options.max_tool_calls * 2 + 10},
        ):
            yield {"ok": None, "output": output}
        completed = [event for event in state.events if event.get("type") == "result_completed"]
        if completed:
            yield {"ok": True, "output": output}
            return
        yield {"ok": False, "errors": [{"message": "resolution did not submit result"}], "output": output}
        return
    yield from _run_fake_model_loop_stream(state, resolution_model, messages, tools)


def build_resolution_graph(resolution_model: Any, tools: list[Any], state: Any):
    model = resolution_model.bind_tools(tools)
    tool_node = ToolNode(tools)

    def call_model(graph_state: MessagesState):
        return {"messages": [model.invoke(graph_state["messages"])]}

    def should_continue(graph_state: MessagesState):
        if len(state.actions) >= state.run_options.max_tool_calls:
            return END
        if any(event.get("type") == "result_completed" for event in state.events):
            return END
        last_message = graph_state["messages"][-1]
        if getattr(last_message, "tool_calls", None):
            return "tools"
        return END

    graph = StateGraph(MessagesState)
    graph.add_node("agent", call_model)
    graph.add_node("tools", tool_node)
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")
    return graph.compile()


def _run_fake_model_loop(state: Any, model: Any, messages: list[Any], tools: list[Any]) -> dict[str, Any]:
    outcome: dict[str, Any] = {"ok": False, "errors": [{"message": "resolution did not run"}]}
    for outcome in _run_fake_model_loop_stream(state, model, messages, tools):
        pass
    return outcome


def _run_fake_model_loop_stream(state: Any, model: Any, messages: list[Any], tools: list[Any]) -> Iterable[dict[str, Any]]:
    tool_map = {getattr(tool, "name", getattr(tool, "__name__", "")): tool for tool in tools}
    for _ in range(state.run_options.max_tool_calls):
        call = model.invoke(messages)
        name = _read(call, "tool_name") or _read(call, "name")
        args = _read(call, "arguments", {}) or _read(call, "args", {}) or {}
        selected = tool_map.get(name)
        if selected is None:
            yield {"ok": False, "errors": [{"message": f"unknown tool: {name}"}]}
            return
        result = selected.invoke(args) if hasattr(selected, "invoke") else selected(**args)
        messages.append({"tool": name, "result": result})
        yield result
        if name == "submit_result" and isinstance(result, dict) and result.get("ok") is True:
            return
    yield {"ok": False, "errors": [{"message": "max_tool_calls exceeded"}]}


def _supports_bind_tools(model: Any) -> bool:
    return callable(getattr(model, "bind_tools", None))


def _task_fields_text(task_spec: Any) -> str:
    lines = []
    for field in getattr(task_spec, "fields", []) or []:
        detail = f"- {field.name}: type={field.type}, required={field.required}"
        variants = getattr(field, "variants", []) or []
        if getattr(field, "type", None) == "enum" and variants:
            variant_text = ", ".join(f"{variant.name}({variant.type})" for variant in variants)
            detail += f", variants={variant_text}"
            detail += ', write_field value shape: {"variant": "<variant name>", "value": <payload>}'
        detail += f", description={field.description or ''}"
        lines.append(detail)
    if getattr(task_spec, "instructions", None):
        lines.append("Instructions: " + task_spec.instructions)
    return "\n".join(lines)


def _read(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


__all__ = ["build_resolution_messages", "run_resolution", "run_resolution_stream", "build_resolution_graph"]
