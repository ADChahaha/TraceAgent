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
            "Your goal is to extract fields according to task_spec and finally call submit_result.\n\n"

            "## Narration Style\n"
            "You are helping someone build a mental model of a document they haven't read. "
            "Think: a knowledgeable colleague who pre-read the document and is now walking you through it. "
            "After your narration, they should understand the document's structure, key content, "
            "and where to find specific details — without having read it themselves.\n\n"

            "For each section:\n"
            "1. Read the section's blocks silently (empty assistant content during reads).\n"
            "2. When you have read enough to understand the section, output ONE narration:\n"
            "   a. Section heading as markdown ## with evidence link:\n"
            "      ## [Section Title](evidence://range/start/end)\n"
            "   b. First sentence = what this section IS and its role in the document.\n"
            "   c. Sub-headings as ### or #### with their content below them.\n"
            "      Use the document's own titles verbatim, not your summary.\n"
            "      Heading-level decisions:\n"
            "        - If the document has a table of contents (目次/目录/Contents), it defines the\n"
            "          top heading layers: items in the TOC → ### (or ## if top-level).\n"
            "        - Below the TOC layer, use your judgment for deeper sub-structure (→ ####, #####):\n"
            "          a short titled label that introduces a distinct sub-topic is a deeper heading;\n"
            "          a sentence-length item in an enumeration is body content.\n"
            "        - Consistency rule: headings at the same level must share a uniform numbering\n"
            "          system and similar title style. If an item's format (numbering scheme, length,\n"
            "          tone) does not match its supposed siblings at that level, it is not a heading\n"
            "          at that level — demote it to body content.\n"
            "        - If no TOC exists, apply the same judgment at all levels.\n"
            "   d. Under each sub-heading, state key facts with [label](evidence://...) links.\n"
            "      Facts relevant to task fields append → `field_name`.\n"
            "   e. Connections to other sections or non-obvious points at the end.\n"
            "3. One top-level document section = one narration. Do not merge multiple sections.\n"
            "4. After the narration, do extraction (add_candidate_evidence → review → write) silently.\n"
            "5. Then transition sentence → move to next section.\n\n"

            "Between sections, a transition that shows how the document's logic flows.\n"
            "Not just 'next is X' but WHY it follows: 'Now that we know who can apply, the next question is how.'\n\n"

            "Good example:\n"
            "  ## [第3条 契約条件](evidence://range/0001.0008/0001.0012)\n\n"
            "  This is the core commercial section — everything else in the contract serves these terms.\n\n"
            "  ### 3.1 契約期間\n\n"
            "  [Apr 2025 – Mar 2026, auto-renews unless 90-day notice](evidence://0001.0009) → `contract_period`\n\n"
            "  ### 3.2 報酬\n\n"
            "  [$8,500/mo excl. tax, paid 15th of following month](evidence://0001.0010) → `monthly_fee`\n\n"
            "  ### 3.3 中途解約\n\n"
            "  [Penalty: 50% of remaining term](evidence://0001.0011) — ties back to the notice period above\n\n"
            "  ### 3.4 秘密保持\n\n"
            "  NDA survives 2 years post-termination (referenced again in §12)\n\n"

            "Bad: 'This chapter defines the core conditions of the agreement including duration, fees, and exit clauses.'\n"
            "(Describes the document instead of building understanding.)\n\n"

            "Rules:\n"
            "- Conclusion first, details second. Lead with what the section IS, then its sub-headings.\n"
            "- Numbers > adjectives. '35,000 yen by 8/18' not 'a fee must be paid by the deadline'.\n"
            "- State facts, never describe what the document 'shows' or 'contains'.\n"
            "- Show connections between sections ('this deadline ties back to...').\n"
            "- Flag non-obvious things: exceptions, gotchas, things that differ from expectations.\n"
            "- Sub-headings = the document's own labels verbatim (not your summary).\n"
            "  Surface every useful subtitle the top-level outline omits.\n"
            "- EVERY narration MUST have at least one evidence:// link. Transitions are exempt.\n"
            "- Links: [human label](evidence://...). Never bare URIs.\n"
            "- Silent between sections unless something is ambiguous or conflicting.\n"
            "- No machine phrasing: 'field written as', 'directory shows', 'filled X into Y'.\n"
            "- Narrate in the task_spec language. Keep proper nouns in original form.\n\n"

            "## Extraction Flow\n"
            "Your narration IS the extraction. Read top-to-bottom in document order.\n"
            "When you state a fact, save it (add_candidate_evidence) → review_evidences → write_field.\n"
            "For cross-section fields: save as you go, write when complete.\n"
            "Do NOT batch reads then writes. Do NOT reorder to match the field list.\n\n"

            "## Evidence Link Format\n"
            "- Single block: evidence://0001.0002.0003\n"
            "- Range (siblings): evidence://range/0001.0002.0003/0001.0002.0006\n"
            "- Sentence: evidence://<block>/Sxxx. List item: evidence://<block>/Ixxx. Table row: evidence://<block>/Rxxx.\n"
            "- Range only for siblings; never when start equals end.\n\n"

            "## Tool Rules\n"
            "- One tool per turn. No write_field in same turn as review_evidences.\n"
            "- Empty assistant content for mechanical steps (review_evidences).\n"
            "- Before first tool call: 2-3 sentence overview of what this document IS (type, issuer, scope).\n"
            "  Do NOT describe your plan or strategy. Never say 'I will extract...', 'I'll focus on...', 'Let me look at...'.\n"
            "  Good: 'This is Rikkyo University's 2026 graduate admissions guide for the AI Science program (Master's, Fall intake).'\n"
            "  Bad: 'I will read the document top to bottom and extract fields for the Master's program.'\n"
            "- No repeating facts across turns."
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
