"""本轮输入 → 直接迭代模型/工具事件 → 编号和终态；调用方取消沿 await 传播。

不创建后台 producer、队列或注册表。关闭事件流时等待内层生成器清理。
"""

from __future__ import annotations

import json
from contextlib import aclosing
from dataclasses import asdict
from typing import Any, AsyncGenerator, AsyncIterator

from langchain_core.messages import AIMessage, ToolMessage

from service.file_extraction_agent.core.loop import run_qa_stream
from service.file_extraction_agent.core.contracts import (
    MessageStarted, MessageDelta, ModelRetry, ModelFailed, QaModel,
)
from service.file_extraction_agent.core.messages import _message_stop_signal, _terminal_stop_signals, visible_text
from service.file_extraction_agent.schemas import DocumentQaMessage, RunOptions


async def stream_completion_events(
    *, workspace: dict[str, Any], messages: list[DocumentQaMessage],
    qa_model: QaModel | None = None,
    run_options: RunOptions | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """仅包装 Agent 普通事件；最终模型失败抛异常，取消向内层传播。"""
    yield {"type": "source_indexed", "tool": "source_index", "result": {"ok": True}}
    async with aclosing(run_qa_stream(
        workspace=workspace, messages=messages, qa_model=qa_model,
        run_options=run_options,
    )) as outputs:
        async for output in outputs:
            if isinstance(output, MessageStarted):
                yield {"type": "model_message.started", "message_id": output.message_id}
            elif isinstance(output, MessageDelta):
                yield {"type": "model_message.delta", "message_id": output.message_id, "delta": output.delta}
            elif isinstance(output, ModelRetry):
                yield {"type": "model_request.retrying", **asdict(output)}
            elif isinstance(output, ModelFailed):
                raise RuntimeError(output.error)
            elif isinstance(output, AIMessage):
                yield _model_message_event(output)
                for call in output.tool_calls:
                    yield {"type": "tool_started", "tool": call["name"], "args": call["args"], "tool_call_id": call["id"]}
            elif isinstance(output, ToolMessage):
                yield _tool_message_event(output)
            else:
                raise TypeError(f"unexpected agent output: {type(output).__name__}")


def _model_message_event(message: AIMessage) -> dict[str, Any]:
    """提取可见文本、工具调用和终止信号，不携带隐藏推理。"""
    stop_signal = _message_stop_signal(message)
    event = {
        "type": "model_message.done",
        "message_id": message.id or "",
        "content": visible_text(message.content),
        "tool_call_count": len(message.tool_calls),
        "tool_calls": [{"id": call["id"], "name": call["name"], "args": call["args"]} for call in message.tool_calls],
        "is_final": not message.tool_calls and stop_signal in _terminal_stop_signals(),
    }
    if stop_signal:
        event["stop_signal"] = stop_signal
    return event


def _tool_message_event(message: ToolMessage) -> dict[str, Any]:
    result = message.artifact
    if result is None:
        try:
            result = json.loads(message.content)
        except (TypeError, json.JSONDecodeError):
            result = message.content
    failed = message.status == "error" or isinstance(result, dict) and result.get("ok") is False
    return {"type": "tool_failed" if failed else "tool_completed", "tool": message.name,
            "args": message.additional_kwargs["tool_args"], "tool_call_id": message.tool_call_id, "result": result}


async def stream_completion(
    workspace: dict[str, Any], qa_model: QaModel,
    messages: list[DocumentQaMessage], run_options: RunOptions | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    """本轮输入 → 普通事件 → 连续编号及终态；取消/关闭直接传播并清理内层流。"""
    seq = 1
    yield {"type": "completion.created", "status": "in_progress", "seq": seq}
    try:
        async with aclosing(stream_completion_events(
            workspace=workspace, messages=messages,
            run_options=run_options, qa_model=qa_model,
        )) as events:
            async for event in events:
                seq += 1
                yield {**event, "seq": seq}
    except Exception as exc:
        yield {"type": "completion.failed", "status": "failed",
               "error_message": str(exc), "seq": seq + 1}
    else:
        yield {"type": "completion.completed", "status": "completed", "seq": seq + 1}


__all__ = ["stream_completion", "stream_completion_events"]
