"""Resolution agent loop for HTML extraction."""

from __future__ import annotations

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
            "Use tools only. Inspect the document with overview/read_element, "
            "query tables with table_extraction, search text with "
            "paragraph_extraction, write fields with set_field, then call finish. "
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
                "Document overview:\n" + str(state.document.tree),
            ]
        )
    )
    return [system, human]


def run_resolution(state: Any, resolution_model: Any) -> dict[str, Any]:
    tools = build_tools(state)
    messages = build_resolution_messages(state)

    if _supports_bind_tools(resolution_model):
        graph = build_resolution_graph(resolution_model, tools, state)
        output = graph.invoke({"messages": messages}, config={"recursion_limit": state.run_options.max_tool_calls + 5})
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

    def should_continue(graph_state: MessagesState):
        if len(state.actions) >= state.run_options.max_tool_calls:
            return END
        messages = graph_state["messages"]
        last_message = messages[-1]
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


def _task_fields_text(task_spec: Any) -> str:
    lines = []
    for field in getattr(task_spec, "fields", []) or []:
        lines.append(
            f"- {field.name}: type={field.type}, required={field.required}, description={field.description or ''}"
        )
    if getattr(task_spec, "instructions", None):
        lines.append("Instructions: " + task_spec.instructions)
    return "\n".join(lines)


def _read(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


__all__ = ["build_resolution_messages", "build_resolution_graph", "run_resolution"]
