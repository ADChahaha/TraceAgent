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
            "Call exactly one tool in each assistant turn. Never emit multiple or parallel tool calls in one turn. "
            "Wait for that tool result before deciding the next tool call. "
            "Tool-specific navigation and argument rules are provided in each tool description. "
            "Every reason is a user-visible action explanation, not hidden reasoning and not evidence. "
            "Every reason must connect the previous action to the next action. "
            "First summarize what the previous action showed, then state the tool action you are about to take. "
            "After a read, say whether the read content appears to support any schema field; "
            "if it may support a field, get inline ids before binding evidence. "
            "Candidate evidence binding is provisional collection, not final classification. "
            "Do not read another path before binding candidate evidence from the current read. "
            "For paragraph evidence, use read on the .md path, then anchors on the same path, then bind_evidence. "
            "For list or table evidence, use the Ixxx/Rxxx ids exposed by read or query_table, then bind_evidence. "
            "You may call bind_evidence multiple times in a row from the same inline source when the same evidence may support multiple fields. "
            "Continue checking supporting, qualifying, and contrary clauses after binding candidate evidence, not before binding it. "
            "Lists expose Ixxx item ids in read output. Tables expose Rxxx row ids in read and query_table output. "
            "as soon as you see text, list items, or table rows that you think may be evidence for a field, "
            "call bind_evidence immediately for that field. "
            "Do not wait until the field value or enum decision is final before binding evidence. "
            "If a field has any bound candidate evidence, call review_field for that field before write_field. "
            "Do not call review_field for fields that have no bound candidate evidence. "
            "write_field submits a field value with final_evidence selected from that field's bound candidate evidence. "
            "final_evidence should include only selectors that are genuinely useful for the submitted value; "
            "drop merely topical, background, duplicate, or weakly related candidate evidence. "
            "Only null-typed fields or null enum variants may submit final_evidence=[]. "
            "For any resolved non-null value or non-null enum variant, submit_result requires non-empty final_evidence. "
            "Mark a field missing with write_field when the document does not mention it. "
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
        return {"messages": [_single_tool_call_message(model.invoke(graph_state["messages"]))]}

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


def _single_tool_call_message(message: Any) -> Any:
    tool_calls = getattr(message, "tool_calls", None)
    if not isinstance(tool_calls, list) or len(tool_calls) <= 1:
        return message
    if callable(getattr(message, "model_copy", None)):
        return message.model_copy(update={"tool_calls": tool_calls[:1]})
    try:
        message.tool_calls = tool_calls[:1]
    except Exception:
        return message
    return message


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
