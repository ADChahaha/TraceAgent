"""protobuf 请求 → 业务校验与模型配置 → manager 事件流 → protobuf 响应。

输入错误在首事件前返回 INVALID_ARGUMENT，初始化异常返回 INTERNAL；
执行异常保留 completion.failed。业务取消立即返回，RPC 断连则通知本轮
CompletionRuntime 并由事件流 finally 清理，避免旧 ID 回调误取消新问答。
"""

import asyncio
import json
import threading
from dataclasses import fields
from typing import Any, AsyncIterator

import grpc

from agent_proto import agent_pb2 as pb
from service.file_extraction_agent.manager import completion_manager
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


def event_message(event: dict[str, Any]) -> pb.CompletionEvent:
    """固定字段按 protobuf 类型传输，动态 args/result 保留 JSON 的数值和空值。"""
    values = {key: value for key, value in event.items()
              if key not in {"args", "result", "tool_calls"}}
    for name in ("args", "result"):
        if name in event:
            values[f"{name}_json"] = _json(event[name])
    if "tool_calls" in event:
        values["tool_calls"] = [
            pb.ToolCall(id=call["id"], name=call["name"], args_json=_json(call["args"]))
            for call in event["tool_calls"]
        ]
    return pb.CompletionEvent(**values)


async def create_chat_completion(request, context) -> AsyncIterator[pb.CompletionEvent]:
    try:
        runtime = await _create_runtime(
            completion_id=request.completion_id,
            resource_path=request.resource_path,
            messages=_messages(request),
            run_options=_options(request.run_options, RunOptions) if request.HasField("run_options") else None,
            model_config=_model_config(request),
        )
    except ValueError as exc:
        await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
    except Exception as exc:
        await context.abort(grpc.StatusCode.INTERNAL, f"completion initialization failed: {exc}")

    events = runtime.stream()
    try:
        context.add_done_callback(lambda _: runtime.disconnect())
        if context.done():
            return
        async for event in events:
            if context.done():
                return
            yield event_message(event)
    finally:
        runtime.disconnect()
        await events.aclose()


async def _create_runtime(**kwargs):
    """线程初始化 → 交接运行时；取消与交接互斥，迟到结果在线程内关闭。"""
    lock = threading.Lock()
    abandoned = False
    runtime = None

    def initialize():
        nonlocal runtime
        created = completion_manager.create(**kwargs)
        with lock:
            if abandoned:
                created.close()
            else:
                runtime = created
        return created

    try:
        return await asyncio.to_thread(initialize)
    except asyncio.CancelledError:
        with lock:
            abandoned = True
            if runtime is not None:
                runtime.close()
        raise


async def cancel_chat_completion(request, context):
    return pb.CompletionResponse(**completion_manager.terminate(request.completion_id))
