"""protobuf 输入 → 校验、资源预检和模型装配 → 请求内事件流 → protobuf 输出。

首事件前参数错误映射 INVALID_ARGUMENT，其他初始化错误映射 INTERNAL。
RPC 取消沿 await 传播，handler 退出时关闭本轮流；不按 ID 注册或查找执行。
"""

import json
import re
from contextlib import aclosing
from dataclasses import fields
from typing import Any, AsyncIterator, Iterator

import grpc
from langchain_core.messages import AIMessage, ToolMessage

from agent_proto import agent_pb2 as pb
from service.file_extraction_agent.core.tools.worker_client import prepare_workspace
from service.file_extraction_agent.core.contracts import (
    AgentOutput, MessageDelta, MessageStarted, ModelFailed, ModelRetry, QaModel,
)
from service.file_extraction_agent.core.loop import run_qa_stream
from service.file_extraction_agent.core.messages import (
    _message_stop_signal, _terminal_stop_signals, visible_text,
)
from service.file_extraction_agent.core.model import build_qa_model
from service.file_extraction_agent.schemas import DocumentQaMessage, ModelConfig, RunOptions


def _options(message, schema):
    return schema(**{field.name: getattr(message, field.name)
                     for field in fields(schema) if message.HasField(field.name)})


def _messages(request):
    messages = []
    for message in request.messages:
        values = {"role": message.role, "content": message.content}
        for field in ("tool_call_id", "name"):
            if message.HasField(field):
                values[field] = getattr(message, field)
        if message.HasField("tool_calls_json"):
            values["tool_calls"] = json.loads(message.tool_calls_json)
        messages.append(DocumentQaMessage.model_validate(values))
    return messages


def _model_config(request):
    if request.HasField("model_config"):
        return _options(request.model_config, ModelConfig)
    names = ("base_url", "api_key", "openai_api_key", "model", "api_transport",
             "temperature", "top_p", "top_k")
    values = {name: getattr(request, name) for name in names if request.HasField(name)}
    if not values:
        return None
    return ModelConfig(
        base_url=values.get("base_url"),
        api_key=values.get("api_key") or values.get("openai_api_key"),
        model_name=values.get("model") or "",
        api_transport=values.get("api_transport") or "responses",
        temperature=values.get("temperature", 0.0),
        top_p=values.get("top_p"), top_k=values.get("top_k"),
    )


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _model_message_event(message: AIMessage) -> pb.CompletionEvent:
    """完整模型消息 → 可见正文、工具调用与终止信号 → protobuf。"""
    stop_signal = _message_stop_signal(message)
    event = pb.CompletionEvent(
        type="model_message.done", message_id=message.id or "",
        content=visible_text(message.content), tool_call_count=len(message.tool_calls),
        tool_calls=[pb.ToolCall(id=call["id"], name=call["name"], args_json=_json(call["args"]))
                    for call in message.tool_calls],
        is_final=not message.tool_calls and stop_signal in _terminal_stop_signals(),
    )
    if stop_signal:
        event.stop_signal = stop_signal
    return event


def _tool_message_event(message: ToolMessage) -> pb.CompletionEvent:
    """工具消息 → 优先 artifact，否则解析正文 → 成功/失败 protobuf，动态数据保留 JSON。"""
    result = message.artifact
    if result is None:
        try:
            result = json.loads(message.content)
        except (TypeError, json.JSONDecodeError):
            result = message.content
    failed = message.status == "error" or isinstance(result, dict) and result.get("ok") is False
    return pb.CompletionEvent(
        type="tool_failed" if failed else "tool_completed", tool=message.name,
        tool_call_id=message.tool_call_id,
        args_json=_json(message.additional_kwargs["tool_args"]), result_json=_json(result),
    )


def _output_events(output: AgentOutput) -> Iterator[pb.CompletionEvent]:
    """单项 core 输出直接编码 protobuf；模型消息另发工具启动事件，最终模型失败抛异常。"""
    if isinstance(output, MessageStarted):
        yield pb.CompletionEvent(type="model_message.started", message_id=output.message_id)
    elif isinstance(output, MessageDelta):
        yield pb.CompletionEvent(type="model_message.delta", message_id=output.message_id, delta=output.delta)
    elif isinstance(output, ModelRetry):
        yield pb.CompletionEvent(
            type="model_request.retrying", message_id=output.message_id,
            attempt=output.attempt, max_attempts=output.max_attempts,
            retry_delay_ms=output.retry_delay_ms, error=output.error,
        )
    elif isinstance(output, ModelFailed):
        raise RuntimeError(output.error)
    elif isinstance(output, AIMessage):
        yield _model_message_event(output)
        for call in output.tool_calls:
            yield pb.CompletionEvent(type="tool_started", tool=call["name"],
                                     tool_call_id=call["id"], args_json=_json(call["args"]))
    elif isinstance(output, ToolMessage):
        yield _tool_message_event(output)
    else:
        raise TypeError(f"unexpected agent output: {type(output).__name__}")


async def stream_completion(
    workspace: dict[str, Any], qa_model: QaModel, messages: list[DocumentQaMessage],
    run_options: RunOptions | None = None,
) -> AsyncIterator[pb.CompletionEvent]:
    """core 流 → 直接编码并编号 protobuf → 唯一终态；取消传播并关闭内层流。"""
    seq = 1
    yield pb.CompletionEvent(type="completion.created", status="in_progress", seq=seq)
    try:
        seq += 1
        yield pb.CompletionEvent(type="source_indexed", tool="source_index", result_json=_json({"ok": True}), seq=seq)
        async with aclosing(run_qa_stream(
            workspace=workspace, qa_model=qa_model, messages=messages, run_options=run_options,
        )) as outputs:
            async for output in outputs:
                for event in _output_events(output):
                    seq += 1
                    event.seq = seq
                    yield event
    except Exception as exc:
        yield pb.CompletionEvent(type="completion.failed", status="failed", error_message=str(exc), seq=seq + 1)
    else:
        yield pb.CompletionEvent(type="completion.completed", status="completed", seq=seq + 1)


async def create_chat_completion(request, context) -> AsyncIterator[pb.CompletionEvent]:
    try:
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", request.completion_id) is None:
            raise ValueError("completion_id must be a safe non-empty identifier")
        messages = _messages(request)
        if not messages:
            raise ValueError("messages must be a non-empty list")
        run_options = _options(request.run_options, RunOptions) if request.HasField("run_options") else None
        model_config = _model_config(request)
        workspace = await prepare_workspace(request.resource_path)
        if not workspace:
            raise ValueError("workspace is required")
        qa_model = build_qa_model(model_config)
    except ValueError as exc:
        await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
    except Exception as exc:
        await context.abort(grpc.StatusCode.INTERNAL, f"completion initialization failed: {exc}")

    async with aclosing(stream_completion(workspace, qa_model, messages, run_options)) as events:
        if context.done():
            return
        async for event in events:
            if context.done():
                return
            yield event
