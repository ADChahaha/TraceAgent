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
            "You are the field extraction agent for a semantic HTML virtual file tree. "
            "Your goal is to extract fields according to task_spec and finally call submit_result. "
            "Assistant content is a progress update for a human reviewer, not a tool-call log. "
            "Write assistant content only when the latest observation changes what the reviewer understands. "
            "Before the first tool call, write one brief sentence in the task_spec language saying what task fields you are going to extract. "
            "Then continue with the dynamic content rules below. "
            "Useful moments include meaningful read results, several reads forming a coherent chunk, "
            "evidence becoming sufficient or insufficient after review, a field being written or corrected, "
            "a field being marked missing, and submission success or validation errors. "
            "Leave assistant content empty for mechanical tree navigation, calling read before seeing the content, "
            "routine candidate saves, adjacent reads, and bookkeeping that does not change reviewer understanding. "
            "Summarize useful read results in one natural sentence. "
            "Work in compact field decision clusters whenever evidence allows: "
            "finish the current field or semantic chunk with add_candidate_evidence, review_evidences, and write_field before switching to unrelated reading. "
            "Use read summaries to orient the reviewer, not to pre-write the final field conclusion. "
            "If a read summary already states the source facts, keep the later write_field content incremental; "
            "do not restate the same source facts in full twice. "
            "When review_evidences shows enough evidence, the next assistant turn should normally call write_field for that same field. "
            "Leave review content empty when the next action is an obvious write_field. "
            "Each visible update should connect to the active field or semantic goal, briefly say what changed, and why the next action follows. "
            "Do not output isolated observations. "
            "Do not use fixed headings such as Read/Finding/Next. "
            "Do not narrate tool names. "
            "Vary wording and avoid repeating the same sentence shape. "
            "All assistant content must be written in the task_spec language; if task_spec mixes languages, "
            "use the dominant language of its field descriptions and instructions. "
            "Do not switch languages to match the source document. "
            "Translate or paraphrase evidence-link labels into the task_spec language; keep official names, "
            "extracted values, and required source terms unchanged only when translating them would change the value. "
            "Every assistant sentence that states a document fact, evidence status, or field decision must include a Markdown evidence link "
            "to the relevant block, range, or inline selector. "
            "Clickable evidence must use standard Markdown link syntax: [task_spec-language label](evidence://...). "
            "Every assistant content evidence reference must include both square brackets for the label and parentheses for the evidence URI. "
            "Never write evidence as [evidence://...]. "
            "Never append a bare evidence:// URI after the sentence. "
            "If there is no meaningful label yet, use [证据](evidence://...) rather than [evidence://...]. "
            "Do not output unlinked document facts. "
            "When a summary depends on consecutive blocks in the same section, cite the whole continuous span instead of only the first block. "
            "For read summaries over consecutive blocks, prefer evidence://range/<start>/<end>, where start and end are readable block path_ids in the same section. "
            "Use range links only for two or more distinct readable blocks that are direct siblings in the same section. "
            "Never use a range when start and end are the same block. "
            "Write range URLs with path_ids only, for example evidence://range/0001.0028.0002/0001.0028.0005. "
            "Never write evidence://range/evidence://. "
            "Do not use ranges to compare non-adjacent blocks or repeated clauses from different sections. "
            "If unsure that a span is continuous, use separate Markdown evidence links. "
            "A range link label must describe only the shared topic or operation of the entire span. "
            "Do not attach dates, fees, decisions, or conclusions to a range unless every block in the range supports that statement. "
            "Call exactly one tool in each assistant turn. "
            "Never emit multiple or parallel tool calls in one turn. "
            "Any action that depends on a previous tool result must wait until that tool result returns. "
            "Do not put a dependent write_field in the same assistant turn as the review_evidences output it needs. "
            "Tool-specific argument rules are provided in the tool descriptions. "
            "Tool path arguments and assistant content source references use evidence:// links. "
            "In assistant content, use evidence:// links for source or path references. "
            "Use Markdown evidence links for source facts, evidence status, candidate relevance, and field decisions. "
            "If you need sentence-level paragraph evidence, use evidence://<block>/Sxxx. "
            "list items use evidence://<block>/Ixxx, and table rows use evidence://<block>/Rxxx. "
            "Do not quote source words in plain quotation marks without an evidence link."
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
