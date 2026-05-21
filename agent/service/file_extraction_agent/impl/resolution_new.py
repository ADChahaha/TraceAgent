"""Resolution loop for virtual-tree file extraction."""

from __future__ import annotations

from typing import Any, Iterable

from langchain_core.messages import (
    HumanMessage,
    SystemMessage,
    message_chunk_to_message,
)
from langgraph.graph import END, StateGraph
from langgraph.graph.message import MessagesState
from langgraph.prebuilt import ToolNode

from service.file_extraction_agent.impl.html_tools import build_tools


def build_resolution_messages(state: Any) -> list[Any]:
    system = SystemMessage(
        content=(
            "You are reading a document to extract specific fields. "
            "Your goal is to extract fields according to task_spec and finally call submit_result. "
            "An outline panel shows the document's section titles to the user (like a table of contents sidebar). "
            "You do not need to list all sections upfront — the outline handles that. "
            "Your narration works like a tour guide: each time you enter a NEW section, briefly explain "
            "what this section is about and what it contains (1-2 sentences + bullets if needed). "
            "Do not explain all sections at the beginning — the user will forget. Explain each section when you arrive there. "
            "Between section introductions, stay mostly silent. Only speak when: "
            "something is non-obvious, ambiguous, conflicting, or missing. "
            "The outline panel shows extracted values and progress — you do not need to report 'field X = Y'. "
            "Speak about the document content, not about your own actions or tool operations. "
            "Never use machine-report phrasing like 'field written as', 'directory shows', 'table gives', 'filled X into Y'. "
            "Use markdown formatting: mix short sentences with bullets carrying actual values when explaining a section. "
            "A good section introduction:\n"
            "  この章は各専攻の募集情報を一つの表にまとめている：\n"
            "  - 専攻ごとに人員・試験区分・日程が横に並ぶ\n"
            "  - 人工知能科学は63名、一般と社会人の2区分\n"
            "  - 表の下に出願受付期間が別途記載\n\n"
            "Always include actual values, numbers, dates — not abstract descriptions of layout. "
            "Do not describe visual positioning ('表の中央', '右側の列'). State what the document says. "
            "Before the first tool call, say in one sentence what this document appears to be about. "
            "Evidence links should use evidence://range/<start>/<end> to cover broad areas. "
            "Each narration block should have one range link whose label names the section or topic. "
            "Clicking it highlights the full relevant area in the original document and syncs the outline. "
            "Example: [募集日程](evidence://range/0001.0017/0001.0019) — covers the whole section. "
            "Do not attach a link to every bullet — one per narration block is enough. "
            "Leave assistant content empty for mechanical navigation, routine candidate saves, "
            "and extraction steps within a section that need no explanation. "
            "Work in compact field decision clusters whenever evidence allows: "
            "finish the current field or semantic chunk with add_candidate_evidence, review_evidences, and write_field before switching to unrelated reading. "
            "Do not restate the same facts twice across turns. "
            "When review_evidences shows enough evidence, call write_field next without additional narration. "
            "Do not narrate tool names or tool operations. "
            "Vary wording naturally. "
            "All assistant content must be in the task_spec language. "
            "Do not switch languages to match the source document. "
            "Keep official names and extracted values in their original form only when translating would change the value. "
            "Use Markdown evidence links [label](evidence://...) to anchor your statements to the document. "
            "The label must be a human-readable topic or section name, NEVER an evidence:// URI. "
            "WRONG: [evidence://0001.0018.0001] — this is broken markdown. "
            "WRONG: 出願受付期間です。[evidence://0001.0017.0001] — bare link after sentence. "
            "RIGHT: [出願受付期間](evidence://range/0001.0017/0001.0018) — topic label with range URI in parentheses. "
            "Not every sentence needs a link — one per narration chunk is enough. "
            "Never write evidence as [evidence://...] or append bare URIs. "
            "For consecutive blocks in the same section, use evidence://range/<start>/<end>. "
            "Use range only for sibling blocks; never when start equals end. "
            "Example: evidence://range/0001.0028.0002/0001.0028.0005. "
            "If unsure a span is continuous, use separate links. "
            "Call exactly one tool per turn. "
            "Do not put a dependent write_field in the same turn as review_evidences. "
            "Sentence evidence: evidence://<block>/Sxxx. "
            "List items: evidence://<block>/Ixxx. Table rows: evidence://<block>/Rxxx."
        )
    )
    human = HumanMessage(
        content="\n\n".join(
            [
                "Task fields:\n" + _task_fields_text(state.task_spec),
                "Use tree first to inspect the virtual file tree, then read specific files from tree output.",
            ]
        )
    )
    return [system, human]


def run_resolution(state: Any, resolution_model: Any) -> dict[str, Any]:
    outcome: dict[str, Any] = {
        "ok": False,
        "errors": [{"message": "resolution did not run"}],
    }
    for outcome in run_resolution_stream(state, resolution_model):
        pass
    return outcome


def run_resolution_stream(
    state: Any, resolution_model: Any
) -> Iterable[dict[str, Any]]:
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
        completed = [
            event for event in state.events if event.get("type") == "result_completed"
        ]
        if completed:
            yield {"ok": True, "output": output}
            return
        yield {
            "ok": False,
            "errors": [{"message": "resolution did not submit result"}],
            "output": output,
        }
        return
    yield from _run_fake_model_loop_stream(state, resolution_model, messages, tools)


def build_resolution_graph(resolution_model: Any, tools: list[Any], state: Any):
    model = _bind_tools_without_parallel(resolution_model, tools)
    tool_node = ToolNode(tools)

    def call_model(graph_state: MessagesState):
        message = _invoke_model_message(model, graph_state["messages"])
        _keep_first_tool_call(message)
        _record_model_message(state, message)
        return {"messages": [message]}

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


def _bind_tools_without_parallel(resolution_model: Any, tools: list[Any]) -> Any:
    try:
        return resolution_model.bind_tools(tools, parallel_tool_calls=False)
    except TypeError:
        return resolution_model.bind_tools(tools)


def _keep_first_tool_call(message: Any) -> Any:
    tool_calls = getattr(message, "tool_calls", None)
    if not isinstance(tool_calls, list) or len(tool_calls) <= 1:
        return message
    first_tool_call = tool_calls[0]
    message.tool_calls = [first_tool_call]
    _keep_first_raw_tool_call(message, first_tool_call)
    return message


def _keep_first_raw_tool_call(message: Any, first_tool_call: Any) -> None:
    additional_kwargs = getattr(message, "additional_kwargs", None)
    if not isinstance(additional_kwargs, dict):
        return
    raw_tool_calls = additional_kwargs.get("tool_calls")
    if not isinstance(raw_tool_calls, list) or len(raw_tool_calls) <= 1:
        return
    first_id = _read(first_tool_call, "id")
    if first_id is None:
        additional_kwargs["tool_calls"] = raw_tool_calls[:1]
        return
    matching_raw_calls = [
        call for call in raw_tool_calls if _read(call, "id") == first_id
    ]
    additional_kwargs["tool_calls"] = (
        matching_raw_calls[:1] if matching_raw_calls else raw_tool_calls[:1]
    )


def _run_fake_model_loop(
    state: Any, model: Any, messages: list[Any], tools: list[Any]
) -> dict[str, Any]:
    outcome: dict[str, Any] = {
        "ok": False,
        "errors": [{"message": "resolution did not run"}],
    }
    for outcome in _run_fake_model_loop_stream(state, model, messages, tools):
        pass
    return outcome


def _run_fake_model_loop_stream(
    state: Any, model: Any, messages: list[Any], tools: list[Any]
) -> Iterable[dict[str, Any]]:
    tool_map = {
        getattr(tool, "name", getattr(tool, "__name__", "")): tool for tool in tools
    }
    for _ in range(state.run_options.max_tool_calls):
        call = model.invoke(messages)
        content = _plain_json(_read(call, "content", ""))
        state.current_model_content = content if isinstance(content, str) else ""
        name = _read(call, "tool_name") or _read(call, "name")
        args = _read(call, "arguments", {}) or _read(call, "args", {}) or {}
        selected = tool_map.get(name)
        if selected is None:
            yield {"ok": False, "errors": [{"message": f"unknown tool: {name}"}]}
            return
        result = (
            selected.invoke(args) if hasattr(selected, "invoke") else selected(**args)
        )
        messages.append({"tool": name, "result": result})
        yield result
        if (
            name == "submit_result"
            and isinstance(result, dict)
            and result.get("ok") is True
        ):
            return
    yield {"ok": False, "errors": [{"message": "max_tool_calls exceeded"}]}


def _supports_bind_tools(model: Any) -> bool:
    return callable(getattr(model, "bind_tools", None))


def _invoke_model_message(model: Any, messages: list[Any]) -> Any:
    errors: list[tuple[str, Exception]] = []
    for attempt in _model_call_attempts(model):
        attempt_name = _read(attempt, "name", "model_call")
        attempt_model = _read(attempt, "model", model)
        use_stream = bool(_read(attempt, "use_stream", True))
        try:
            if use_stream:
                return _stream_model_message(attempt_model, messages)
            return attempt_model.invoke(messages)
        except Exception as exc:
            errors.append((str(attempt_name), exc))
    details = "; ".join(
        f"{name}: {type(error).__name__}: {error}" for name, error in errors
    )
    raise RuntimeError(f"all model call attempts failed: {details}")


def _model_call_attempts(model: Any) -> list[Any]:
    attempts = getattr(model, "model_call_attempts", None)
    if callable(attempts):
        return list(attempts())
    return [
        {"name": "stream", "model": model, "use_stream": True},
        {"name": "invoke", "model": model, "use_stream": False},
    ]


def _stream_model_message(model: Any, messages: list[Any]) -> Any:
    stream = getattr(model, "stream", None)
    if not callable(stream):
        raise RuntimeError("model does not support stream")
    streamed_message: Any = None
    for chunk in stream(messages):
        streamed_message = (
            chunk if streamed_message is None else streamed_message + chunk
        )
    if streamed_message is None:
        raise RuntimeError("model stream returned no chunks")
    return message_chunk_to_message(streamed_message)


def _record_model_message(state: Any, message: Any) -> None:
    tool_calls = getattr(message, "tool_calls", None)
    if not isinstance(tool_calls, list):
        tool_calls = []
    content = _message_content_text(getattr(message, "content", ""))
    state.current_model_content = content if isinstance(content, str) else ""
    state.events.append(
        {
            "seq": state.next_seq,
            "type": "model_message",
            "content": content,
            "tool_call_count": len(tool_calls),
            "tool_calls": [_tool_call_summary(call) for call in tool_calls],
        }
    )
    state.next_seq += 1


def _message_content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
            continue
        if not isinstance(item, dict):
            continue
        if item.get("type") == "text" and isinstance(item.get("text"), str):
            parts.append(item["text"])
    return "".join(parts)


def _task_fields_text(task_spec: Any) -> str:
    lines = []
    for field in getattr(task_spec, "fields", []) or []:
        detail = f"- {field.name}: type={field.type}, required={field.required}"
        variants = getattr(field, "variants", []) or []
        if getattr(field, "type", None) == "enum" and variants:
            variant_text = ", ".join(
                f"{variant.name}({variant.type})" for variant in variants
            )
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


def _tool_call_summary(call: Any) -> dict[str, Any]:
    summary = {
        "id": _read(call, "id"),
        "name": _read(call, "name"),
        "args": _plain_json(_read(call, "args", {})),
    }
    return {key: value for key, value in summary.items() if value not in (None, "")}


def _plain_json(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, dict):
        return {str(key): _plain_json(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_plain_json(item) for item in value]
    return str(value)


__all__ = [
    "build_resolution_messages",
    "run_resolution",
    "run_resolution_stream",
    "build_resolution_graph",
    "_invoke_model_message",
]
