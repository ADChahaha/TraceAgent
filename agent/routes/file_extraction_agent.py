"""protobuf 输入 → 普通业务参数 → application 事件流 → protobuf；映射 RPC 错误并传播取消。"""

import json
from contextlib import aclosing
from dataclasses import fields
from typing import AsyncIterator

import grpc
from agent_proto import agent_pb2 as pb
from service.file_extraction_agent import application
from service.file_extraction_agent.schemas import (
    CompletionEvent, DocumentQaMessage, ModelConfig, ResourceRef, RunOptions, Unset,
)


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


def encode_completion_event(event: CompletionEvent) -> pb.CompletionEvent:
    """保留可选字段缺省、显式 false/零值，以及 JSON null 和大整数。"""
    values = {field.name: getattr(event, field.name) for field in fields(event)
              if field.name not in {"args", "result", "tool_calls"}
              and getattr(event, field.name) is not None}
    values["tool_calls"] = [pb.ToolCall(id=call.id, name=call.name, args_json=_json(call.args))
                            for call in event.tool_calls]
    for name in ("args", "result"):
        value = getattr(event, name)
        if value is not Unset.VALUE:
            values[f"{name}_json"] = _json(value)
    return pb.CompletionEvent(**values)


async def encode_completion_stream(events):
    """编码业务流；编码异常回传业务生成器收口，退出时关闭业务流。"""
    async with aclosing(events):
        async for event in events:
            try:
                encoded = encode_completion_event(event)
            except Exception as exc:
                encoded = encode_completion_event(await events.athrow(exc))
            yield encoded


async def create_chat_completion(request, context) -> AsyncIterator[pb.CompletionEvent]:
    try:
        messages = _messages(request)
        refs = [ResourceRef(type=ref.type, location=ref.location) for ref in request.resource_path]
        model_config = _model_config(request)
        run_options = _options(request.run_options, RunOptions) if request.HasField("run_options") else None
        async with aclosing(encode_completion_stream(application.stream_completion(
            completion_id=request.completion_id, resource_refs=refs, messages=messages,
            model_config=model_config, run_options=run_options,
        ))) as events:
            if context.done():
                return
            async for event in events:
                if context.done():
                    return
                yield event
    except ValueError as exc:
        await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
    except Exception as exc:
        await context.abort(grpc.StatusCode.INTERNAL, f"completion initialization failed: {exc}")
