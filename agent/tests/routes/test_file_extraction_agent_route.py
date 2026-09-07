"""真实 RPC 请求 → 原 manager/runtime → protobuf 事件，验证校验、取消及断连。"""

import asyncio
from tests.async_helpers import async_items
import json
import threading
import time

import grpc
import pytest

from agent_proto import agent_pb2 as pb
from routes import file_extraction_agent as qa_routes
from service.file_extraction_agent import manager as manager_module
from service.file_extraction_agent import completion_runtime as runtime_module
from service.file_extraction_agent.manager import CompletionManager
from service.file_extraction_agent.schemas import RunOptions


@pytest.fixture
def manager(monkeypatch):
    instance = CompletionManager()
    monkeypatch.setattr(qa_routes, "completion_manager", instance)
    monkeypatch.setattr(manager_module, "validate_resource", lambda path: None)
    monkeypatch.setattr(manager_module, "build_qa_model", lambda config: object())
    return instance


def request(**fields):
    values = dict(completion_id="cmp_rpc", resource_path="D:/resources/res_test",
                  messages=[pb.QaMessage(role="user", content="问题")])
    values.update(fields)
    return pb.ChatCompletionRequest(**values)


def test_many_waiting_streams_keep_control_rpcs_available(rpc, manager, monkeypatch):
    """二十条活动流等待时，取消和能力查询仍能立即处理。"""
    release = threading.Event()

    async def events(**kwargs):
        yield {"type": "completion.created"}
        await asyncio.Event().wait()

    monkeypatch.setattr(runtime_module, "stream_completion_events", events)
    streams = []
    try:
        for i in range(20):
            stream = rpc.ChatCompletion(request(completion_id=f"many{i}"), timeout=10)
            streams.append(stream)
            assert next(stream).type == "completion.created"
        assert rpc.GetCapabilities(pb.Empty(), timeout=1).supported_file_types
        assert rpc.CancelCompletion(pb.CompletionRequest(completion_id="many0"), timeout=1).status == "cancelling"
        assert next(streams[0]).type == "completion.cancelled"
    finally:
        for stream in streams:
            stream.cancel()
        release.set()


def test_initialization_cleanup_survives_event_loop_shutdown(manager, monkeypatch):
    """初始化期间断连并关闭事件循环，迟到的初始化结果也必须释放。"""
    started = threading.Event()
    release = threading.Event()

    def build(config):
        started.set()
        assert release.wait(5)
        return object()

    monkeypatch.setattr(manager_module, "build_qa_model", build)

    async def run():
        stream = qa_routes.create_chat_completion(request(), None)
        task = asyncio.create_task(anext(stream))
        try:
            assert await asyncio.to_thread(started.wait, 2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            asyncio.get_running_loop().call_later(0.1, release.set)

    try:
        asyncio.run(run())
        assert manager.get_status("cmp_rpc") is None
    finally:
        release.set()


def test_chat_streams_typed_events_and_preserves_json(rpc, manager, monkeypatch):
    """事件按序逐条传输，动态 JSON 保留大整数、空值和特殊字符。"""
    payload = {"number": 2 ** 60 + 1, "text": '中文\n"引号"', "null": None}
    async def events(**kwargs):
        yield {"type": "model_message", "content": "回答", "is_final": False,
               "tool_call_count": 1, "tool_calls": [{"id": "call1", "name": "read", "args": payload}]}
        yield {"type": "tool_completed", "tool": "read", "tool_call_id": "call1",
               "args": payload, "result": payload}
        yield {"type": "completion.completed", "status": "completed"}
    monkeypatch.setattr(runtime_module, "stream_completion_events", events)
    result = list(rpc.ChatCompletion(request(), timeout=5))
    assert [e.seq for e in result] == [1, 2, 3]
    assert result[0].HasField("is_final") and result[0].is_final is False
    assert json.loads(result[0].tool_calls[0].args_json) == payload
    assert json.loads(result[1].result_json) == payload
    assert json.loads(result[1].args_json) == payload
    assert result[-1].type == "completion.completed"
    assert "completion_id" not in result[0].DESCRIPTOR.fields_by_name


def test_chat_preserves_history_options_and_model_defaults(rpc, manager, monkeypatch):
    """历史工具消息、显式零值和未传配置的默认值保持一致。"""
    seen = {}
    def build(config):
        seen["config"] = config
        return object()
    async def events(**kwargs):
        seen.update(kwargs)
        yield {"type": "completion.completed", "status": "completed"}
    monkeypatch.setattr(manager_module, "build_qa_model", build)
    monkeypatch.setattr(runtime_module, "stream_completion_events", events)
    history = [{"id": "a", "name": "read", "args": {"path": "a.md"}}]
    messages = [
        pb.QaMessage(role="assistant", content="", tool_calls_json=json.dumps(history)),
        pb.QaMessage(role="tool", content="结果", tool_call_id="a", name="read"),
    ]
    list(rpc.ChatCompletion(request(messages=messages, run_options=pb.RunOptions(max_tool_calls=0),
                                   model_config=pb.ModelConfig(top_k=0, temperature=0)), timeout=5))
    assert seen["messages"][0].tool_calls == history
    assert seen["messages"][1].tool_call_id == "a"
    assert seen["run_options"] == RunOptions(max_tool_calls=0)
    assert seen["config"].top_k == 0
    assert seen["config"].api_transport == "responses"
    assert seen["config"].request_timeout is None
    list(rpc.ChatCompletion(request(), timeout=5))
    assert seen["config"] is None and seen["run_options"] is None


def test_chat_model_override_precedence(rpc, manager, monkeypatch):
    """兼容扁平模型参数，嵌套模型配置优先。"""
    configs = []
    monkeypatch.setattr(manager_module, "build_qa_model", lambda config: configs.append(config))
    monkeypatch.setattr(runtime_module, "stream_completion_events",
                        lambda **kwargs: async_items([{"type": "completion.completed"}]))
    flat = dict(base_url="https://example.com/v1", openai_api_key="key", model="qa",
                api_transport="chat_completions", temperature=0.2, top_p=0.9, top_k=40)
    list(rpc.ChatCompletion(request(**flat), timeout=5))
    assert configs[-1].api_key == "key" and configs[-1].model_name == "qa"
    assert configs[-1].top_p == 0.9 and configs[-1].top_k == 40
    list(rpc.ChatCompletion(request(**flat, model_config=pb.ModelConfig(model_name="nested")), timeout=5))
    assert configs[-1].model_name == "nested" and configs[-1].api_key is None


@pytest.mark.parametrize("fields", [
    {"completion_id": "../bad"}, {"messages": []},
    {"messages": [pb.QaMessage(role="unknown", content="问题")]},
    {"messages": [pb.QaMessage(role="tool", content="结果")]},
    {"messages": [pb.QaMessage(role="assistant", tool_calls_json="{bad")]},
    {"messages": [pb.QaMessage(role="assistant", tool_calls_json="{}")]},
])
def test_chat_rejects_invalid_input_before_first_event(rpc, manager, fields):
    """无效 ID、角色、历史工具 JSON 或空消息在首事件前返回 INVALID_ARGUMENT。"""
    with pytest.raises(grpc.RpcError) as error:
        next(rpc.ChatCompletion(request(**fields), timeout=5))
    assert error.value.code() == grpc.StatusCode.INVALID_ARGUMENT
    assert manager._completions == {}


def test_chat_runtime_failure_is_terminal_event(rpc, manager, monkeypatch):
    """开始执行后的异常通过 completion.failed 保留原始错误文本。"""
    def fail(**kwargs):
        raise RuntimeError('失败\n"原因"')
    monkeypatch.setattr(runtime_module, "stream_completion_events", fail)
    events = list(rpc.ChatCompletion(request(), timeout=5))
    assert len(events) == 1
    assert events[0].type == "completion.failed"
    assert events[0].error_message == '失败\n"原因"'


def test_cancel_returns_before_tool_batch_and_stream_drains(rpc, manager, monkeypatch):
    """取消 RPC 先返回 cancelling，工具结果补齐后原流仅发一个取消终态。"""
    release = threading.Event()
    started = threading.Event()
    async def events(**kwargs):
        yield {"type": "model_message", "tool_calls": [{"id": "call1", "name": "read", "args": {}}]}
        started.set()
        assert await asyncio.to_thread(release.wait, 5)
        yield {"type": "tool_completed", "tool": "read", "tool_call_id": "call1", "result": {"ok": True}}
        yield {"type": "completion.cancelled", "status": "cancelled"}
    monkeypatch.setattr(runtime_module, "stream_completion_events", events)
    stream = rpc.ChatCompletion(request(), timeout=8)
    try:
        assert next(stream).type == "model_message"
        assert started.wait(2)
        cancel = rpc.CancelCompletion(pb.CompletionRequest(completion_id="cmp_rpc"), timeout=1)
        assert cancel.status == "cancelling"
        assert not release.is_set()
        assert manager.get_status("cmp_rpc")["status"] == "cancelling"
        assert rpc.CancelCompletion(pb.CompletionRequest(completion_id="cmp_rpc"), timeout=1).status == "cancelling"
        release.set()
        remaining = list(stream)
        assert [e.type for e in remaining] == ["tool_completed", "completion.cancelled"]
        assert [e.seq for e in remaining] == [2, 3]
    finally:
        release.set()
        stream.cancel()


@pytest.mark.parametrize("deadline", [False, True])
def test_transport_cancel_or_deadline_cleans_runtime(rpc, manager, monkeypatch, deadline):
    """RPC 取消和超时唤醒阻塞消费者并释放注册项，后台观察停止信号。"""
    release = threading.Event()
    stopped = threading.Event()
    async def events(**kwargs):
        yield {"type": "completion.created", "status": "in_progress"}
        try:
            assert await asyncio.to_thread(release.wait, 5)
            assert kwargs["should_stop"]()
        finally:
            stopped.set()
    monkeypatch.setattr(runtime_module, "stream_completion_events", events)
    stream = rpc.ChatCompletion(request(), timeout=0.5 if deadline else 5)
    try:
        assert next(stream).type == "completion.created"
        if not deadline:
            assert stream.cancel()
        with pytest.raises(grpc.RpcError) as error:
            next(stream)
        assert error.value.code() == (grpc.StatusCode.DEADLINE_EXCEEDED if deadline else grpc.StatusCode.CANCELLED)
        limit = time.monotonic() + 2
        while manager.get_status("cmp_rpc") is not None and time.monotonic() < limit:
            time.sleep(0.01)
        assert manager.get_status("cmp_rpc") is None
    finally:
        release.set()
        stream.cancel()
        assert stopped.wait(2)


def test_duplicate_id_does_not_cancel_existing_stream(rpc, manager, monkeypatch):
    """重复 ID 请求失败，原运行时仍可独立取消。"""
    release = threading.Event()
    async def events(**kwargs):
        yield {"type": "completion.created"}
        await asyncio.to_thread(release.wait, 5)
    monkeypatch.setattr(runtime_module, "stream_completion_events", events)
    stream = rpc.ChatCompletion(request(), timeout=5)
    try:
        next(stream)
        with pytest.raises(grpc.RpcError) as error:
            next(rpc.ChatCompletion(request(), timeout=2))
        assert error.value.code() == grpc.StatusCode.INVALID_ARGUMENT
        assert manager.get_status("cmp_rpc")["status"] == "in_progress"
        assert rpc.CancelCompletion(pb.CompletionRequest(completion_id="cmp_rpc"), timeout=1).status == "cancelling"
        assert list(stream)[-1].type == "completion.cancelled"
    finally:
        release.set()
        stream.cancel()


def test_cancel_unknown_returns_not_found(rpc, manager):
    """未知取消返回 not_found。"""
    query = pb.CompletionRequest(completion_id="missing")
    assert rpc.CancelCompletion(query, timeout=2).status == "not_found"


def test_completion_query_is_not_exposed(rpc, rpc_channel):
    """协议和客户端不暴露问答查询，旧 RPC 路径也不注册处理器。"""
    assert "GetCompletion" not in pb.DESCRIPTOR.services_by_name["AgentService"].methods_by_name
    assert not hasattr(rpc, "GetCompletion")
    query = rpc_channel.unary_unary(
        "/traceagent.v1.AgentService/GetCompletion",
        request_serializer=pb.CompletionRequest.SerializeToString,
        response_deserializer=pb.CompletionResponse.FromString,
    )
    with pytest.raises(grpc.RpcError) as error:
        query(pb.CompletionRequest(completion_id="missing"), timeout=2)
    assert error.value.code() == grpc.StatusCode.UNIMPLEMENTED


def test_legacy_request_fields_are_not_in_protocol():
    """新契约只接收资源路径，不定义旧业务字段。"""
    fields = pb.ChatCompletionRequest.DESCRIPTOR.fields_by_name
    assert not {"documents", "metadata", "memory", "task_spec"} & set(fields.keys())
