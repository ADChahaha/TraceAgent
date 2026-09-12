"""问答业务入口：校验普通参数 → 预检资源、装配模型 → core 执行 → 类型化事件与唯一终态。

初始化失败直接抛 ValueError/其他异常；执行失败输出 completion.failed。
取消与 GeneratorExit 原样传播，aclosing 逐层释放执行流。
"""

import json
import re
from contextlib import aclosing
from typing import Any, AsyncIterator, Iterator

from langchain_core.messages import AIMessage, ToolMessage
from service.file_extraction_agent.core.tools.worker_client import prepare_workspace
from service.file_extraction_agent.core.contracts import (
    AgentOutput, MessageDelta, MessageStarted, ModelFailed, ModelRetry, QaModel,
)
from service.file_extraction_agent.core.loop import run_qa_stream
from service.file_extraction_agent.core.messages import (
    _message_stop_signal, _terminal_stop_signals, visible_text,
)
from service.file_extraction_agent.core.model import build_qa_model
from service.file_extraction_agent.schemas import (
    CompletionEvent, CompletionToolCall, DocumentQaMessage, ModelConfig, ResourceRefs, RunOptions,
)


def _json(value):
    """验证动态数据可无损表示为标准 JSON；保留原始值供传输层编码。"""
    json.dumps(value, ensure_ascii=False, allow_nan=False)
    return value


def _model_message_event(message: AIMessage) -> CompletionEvent:
    """完整模型消息 → 可见正文、工具调用与终止信号 → 业务事件。"""
    stop_signal = _message_stop_signal(message)
    event = CompletionEvent(
        type="model_message.done", message_id=message.id or "",
        content=visible_text(message.content), tool_call_count=len(message.tool_calls),
        tool_calls=[CompletionToolCall(id=call["id"], name=call["name"], args=_json(call["args"]))
                    for call in message.tool_calls],
        is_final=not message.tool_calls and stop_signal in _terminal_stop_signals(),
    )
    if stop_signal:
        event.stop_signal = stop_signal
    return event


def _tool_message_event(message: ToolMessage) -> CompletionEvent:
    """工具消息 → 优先 artifact，否则解析正文 → 成功/失败 业务事件，动态数据保留 JSON。"""
    result = message.artifact
    if result is None:
        try:
            result = json.loads(message.content)
        except (TypeError, json.JSONDecodeError):
            result = message.content
    failed = message.status == "error" or isinstance(result, dict) and result.get("ok") is False
    return CompletionEvent(
        type="tool_failed" if failed else "tool_completed", tool=message.name,
        tool_call_id=message.tool_call_id,
        args=_json(message.additional_kwargs["tool_args"]), result=_json(result),
    )


def _output_events(output: AgentOutput) -> Iterator[CompletionEvent]:
    """单项 core 输出直接编码 业务事件；模型消息另发工具启动事件，最终模型失败抛异常。"""
    if isinstance(output, MessageStarted):
        yield CompletionEvent(type="model_message.started", message_id=output.message_id)
    elif isinstance(output, MessageDelta):
        yield CompletionEvent(type="model_message.delta", message_id=output.message_id, delta=output.delta)
    elif isinstance(output, ModelRetry):
        yield CompletionEvent(
            type="model_request.retrying", message_id=output.message_id,
            attempt=output.attempt, max_attempts=output.max_attempts,
            retry_delay_ms=output.retry_delay_ms, error=output.error,
        )
    elif isinstance(output, ModelFailed):
        raise RuntimeError(output.error)
    elif isinstance(output, AIMessage):
        yield _model_message_event(output)
        for call in output.tool_calls:
            yield CompletionEvent(type="tool_started", tool=call["name"],
                                     tool_call_id=call["id"], args=_json(call["args"]))
    elif isinstance(output, ToolMessage):
        yield _tool_message_event(output)
    else:
        raise TypeError(f"unexpected agent output: {type(output).__name__}")


async def stream_execution(
    workspace: dict[str, Any], qa_model: QaModel, messages: list[DocumentQaMessage],
    run_options: RunOptions | None = None,
) -> AsyncIterator[CompletionEvent]:
    """core 流 → 归一化并编号 业务事件 → 唯一终态；取消传播并关闭内层流。"""
    seq = 1
    yield CompletionEvent(type="completion.created", status="in_progress", seq=seq)
    try:
        seq += 1
        yield CompletionEvent(type="source_indexed", tool="source_index", result=_json({"ok": True}), seq=seq)
        async with aclosing(run_qa_stream(
            workspace=workspace, qa_model=qa_model, messages=messages, run_options=run_options,
        )) as outputs:
            async for output in outputs:
                for event in _output_events(output):
                    seq += 1
                    event.seq = seq
                    try:
                        yield event
                    except Exception:
                        # 消费方未能编码本条事件，该序号由失败终态复用。
                        seq -= 1
                        raise
    except Exception as exc:
        yield CompletionEvent(type="completion.failed", status="failed", error_message=str(exc), seq=seq + 1)
    else:
        yield CompletionEvent(type="completion.completed", status="completed", seq=seq + 1)


async def stream_completion(
    *, completion_id: str, resource_refs: ResourceRefs,
    messages: list[DocumentQaMessage], model_config: ModelConfig | None = None,
    run_options: RunOptions | None = None,
) -> AsyncIterator[CompletionEvent]:
    """校验 ID/消息 → prepare_workspace → build_qa_model → stream_execution；初始化先于首事件。"""
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", completion_id) is None:
        raise ValueError("completion_id must be a safe non-empty identifier")
    if not messages:
        raise ValueError("messages must be a non-empty list")
    workspace = await prepare_workspace(resource_refs)
    if not workspace:
        raise ValueError("workspace is required")
    qa_model = build_qa_model(model_config)
    async with aclosing(stream_execution(workspace, qa_model, messages, run_options)) as events:
        async for event in events:
            try:
                yield event
            except Exception as exc:
                # 将协议适配失败交给同一个业务终态出口，不在路由生成终态。
                yield await events.athrow(exc)
