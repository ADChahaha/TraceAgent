"""Resolution loop for document QA completions."""

from __future__ import annotations

from typing import Any, Iterable

from langchain_core.messages import HumanMessage, SystemMessage, message_chunk_to_message
from langgraph.graph import END, StateGraph
from langgraph.graph.message import MessagesState
from langgraph.prebuilt import ToolNode

from service.file_extraction_agent.impl.html_tools import build_tools


def build_resolution_messages(state: Any) -> list[Any]:
    system = SystemMessage(
        content=(
            "You are reading documents in a virtual repository to answer user questions. "
            "Navigate the document tree using the provided tools, then answer with evidence.\n\n"

            "## Narration Style\n"
            "You are a colleague investigating documents in real time. Show your full "
            "thought process — every turn must have visible reasoning before the tool call.\n\n"
            "Each turn follows this pattern:\n"
            "1. Analyze: what do I need to find? What keywords or sections are relevant?\n"
            "2. React: what did the previous result tell me? Is it enough?\n"
            "3. Decide: what's my next move and why?\n\n"
            "Never call a tool silently. Always show your thinking first.\n\n"
            "Example investigation (user asked about program requirements):\n\n"
            "  'I need to find program requirements. Let me search for keywords "
            "like \"requirements\" or \"eligibility\" to locate the relevant section.'\n"
            "  → [grep call]\n\n"
            "  'Got 3 hits. The most relevant is in [Section 4](evidence://0001.0004) "
            "which seems to cover program-specific requirements. But the preview only "
            "shows a partial sentence — I need more context to understand the full "
            "eligibility criteria.'\n"
            "  → [read call]\n\n"
            "  'This paragraph lists [GPA 3.0 and TOEFL 80](evidence://0001.0004.0003/S001) "
            "as minimum requirements. But it references \"Appendix 2\" for additional documents. "
            "That table might have more conditions — let me find it.'\n"
            "  → [grep call]\n\n"
            "  'Found [Appendix 2](evidence://0001.0007.0002) — it's a checklist of required "
            "documents. Nothing about additional academic requirements, just paperwork. "
            "So the core requirements are GPA and TOEFL only.'\n"
            "  → [final answer]\n\n"
            "Key principles:\n"
            "- Think like a researcher: hypothesize, search, evaluate, iterate.\n"
            "- Say what's missing or insufficient, not just what you found.\n"
            "- When a result is partial, explain what's still unclear and where to look.\n"
            "- Cite evidence inline as you discover it, not just in the final answer.\n"
            "- The journey IS the value — users want to see HOW you found the answer.\n\n"

            "## Evidence Rules\n"
            "Every factual statement about the document MUST include a Markdown evidence "
            "link when first stated. No exceptions.\n\n"
            "Format:\n"
            "- Block link: [label](evidence://0001.0002.0003)\n"
            "- Range link: [label](evidence://range/0001.0002.0003/0001.0002.0006)\n"
            "- Inline sentence: [label](evidence://0001.0002.0003/S001)\n"
            "- Inline list item: [label](evidence://0001.0002.0003/I001)\n"
            "- Inline table row: [label](evidence://0001.0002.0003/R001)\n\n"
            "Use block links for section-level observations. Use inline links for "
            "concrete facts: dates, amounts, conditions, names, exceptions.\n"
            "Never use bare evidence:// URIs — always wrap in [label](...).\n\n"

            "## Final Answer\n"
            "- Answer in the same language as the user's question.\n"
            "- Conclusion first, then supporting details with evidence links.\n"
            "- Numbers and specifics over vague adjectives.\n"
            "- State facts directly. Never say 'the document shows' or 'it states that'.\n"
            "- If the document does not contain the answer, say so explicitly.\n\n"

            "## Discipline\n"
            "- One tool per turn.\n"
            "- Do not repeat reads of the same block.\n"
            "- After reading enough to answer, stop investigating and give your answer.\n"
            "- Your final message must be text (the answer), not a tool call."
        )
    )
    parts = [
        "Conversation:\n" + _messages_text(state.messages),
    ]
    memory_text = _memory_text(state.memory)
    if memory_text.strip():
        parts.append("Context from prior turns:\n" + memory_text)
    parts.append(
        "Investigate the documents using the tools, then end with a concise "
        "final answer as your last assistant message."
    )
    return [system, HumanMessage(content="\n\n".join(parts))]


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
        yield {"ok": True, "output": output}
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
    matching_raw_calls = [call for call in raw_tool_calls if _read(call, "id") == first_id]
    additional_kwargs["tool_calls"] = matching_raw_calls[:1] if matching_raw_calls else raw_tool_calls[:1]


def _run_fake_model_loop_stream(
    state: Any,
    model: Any,
    messages: list[Any],
    tools: list[Any],
) -> Iterable[dict[str, Any]]:
    tool_map = {getattr(tool, "name", getattr(tool, "__name__", "")): tool for tool in tools}
    for _ in range(state.run_options.max_tool_calls):
        call = model.invoke(messages)
        content = _plain_json(_read(call, "content", ""))
        state.current_model_content = content if isinstance(content, str) else ""
        name = _read(call, "tool_name") or _read(call, "name")
        args = _read(call, "arguments", {}) or _read(call, "args", {}) or {}
        if content:
            _record_plain_model_message(state, content, name, args)
        if not name:
            yield {"ok": True, "output": call}
            return
        selected = tool_map.get(name)
        if selected is None:
            yield {"ok": False, "errors": [{"message": f"unknown tool: {name}"}]}
            return
        result = selected.invoke(args) if hasattr(selected, "invoke") else selected(**args)
        messages.append({"tool": name, "result": result})
        yield result
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
    details = "; ".join(f"{name}: {type(error).__name__}: {error}" for name, error in errors)
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
        streamed_message = chunk if streamed_message is None else streamed_message + chunk
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


def _record_plain_model_message(state: Any, content: str, tool_name: str | None, args: dict[str, Any]) -> None:
    state.events.append(
        {
            "seq": state.next_seq,
            "type": "model_message",
            "content": content,
            "tool_call_count": 1 if tool_name else 0,
            "tool_calls": ([{"name": tool_name, "args": _plain_json(args)}] if tool_name else []),
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


def _messages_text(messages: list[Any]) -> str:
    lines = []
    for message in messages:
        role = getattr(message, "role", "")
        content = getattr(message, "content", "")
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _memory_text(memory: Any) -> str:
    sections: list[str] = []
    prior_answers = getattr(memory, "prior_answers", []) or []
    if prior_answers:
        sections.append("Previous answers in this session:\n" + "\n---\n".join(str(a) for a in prior_answers[-5:]))
    open_threads = getattr(memory, "open_threads", []) or []
    if open_threads:
        sections.append("Open threads: " + "; ".join(str(t) for t in open_threads))
    return "\n\n".join(sections)


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
    "run_resolution_stream",
    "build_resolution_graph",
    "_invoke_model_message",
]
