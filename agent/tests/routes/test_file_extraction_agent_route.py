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

    async def fake_prepare(resource_path):
        return {"stub": True}

    monkeypatch.setattr(qa_routes, "prepare_workspace", fake_prepare)
    monkeypatch.setattr(manager_module, "build_qa_model", lambda config: object())
    return instance


def request(**fields):
    values = dict(completion_id="cmp_rpc",
                  resource_path=[pb.ResourceRef(type="documents", location="s3://res_test/documents"),
                                 pb.ResourceRef(type="index", location="s3://res_test/index")],
                  messages=[pb.QaMessage(role="user", content="问题")])
    values.update(fields)
    return pb.ChatCompletionRequest(**values)


@pytest.mark.parametrize("cancel", [False, True])
def test_real_graph_streams_native_chunks_and_retry_over_rpc(rpc, manager, monkeypatch, cancel):
    """真实图和模型回调 → RPC 增量；验证重试字段及生成期间业务取消。"""
    from tests.file_extraction_agent.test_streaming_retry import StreamingModel
    from service.file_extraction_agent.core import loop

    model = StreamingModel(failures=0 if cancel else 1)
    if not cancel:
        model._release.set()
    monkeypatch.setattr(manager_module, "build_qa_model", lambda config: model)
    monkeypatch.setattr(loop, "build_tools", lambda workspace: [])
    stream = rpc.ChatCompletion(request(), timeout=5)
    events = []
    try:
        for event in stream:
            events.append(event)
            if cancel and event.type == "model_message.delta":
                assert not model._closed.is_set()
                response = rpc.CancelCompletion(pb.CompletionRequest(completion_id="cmp_rpc"), timeout=1)
                assert response.status == "cancelling"
    finally:
        stream.cancel()
    assert [e.seq for e in events] == list(range(1, len(events) + 1))
    assert not any(e.type == "completion.cancelled" for e in events)
    if not cancel:
        assert events[-1].type == "completion.completed"
    if cancel:
        assert not any(e.type == "model_message.done" for e in events)
        assert model._calls == 1
    else:
        retry = next(e for e in events if e.type == "model_request.retrying")
        assert retry.attempt == 2 and retry.max_attempts == 5
        assert 375 <= retry.retry_delay_ms <= 500
        done = next(e for e in events if e.type == "model_message.done")
        assert done.content == "前半后半" and done.message_id != retry.message_id
        assert model._calls == 2


def test_many_waiting_streams_keep_control_rpcs_available(rpc, manager, monkeypatch):
    """二十条活动流等待时，取消仍能立即处理。"""
    release = threading.Event()

    async def events(**kwargs):
        if False:
            yield {}
        await asyncio.Event().wait()

    monkeypatch.setattr(runtime_module, "stream_completion_events", events)
    streams = []
    try:
        for i in range(20):
            stream = rpc.ChatCompletion(request(completion_id=f"many{i}"), timeout=10)
            streams.append(stream)
            assert next(stream).type == "completion.created"
        assert rpc.CancelCompletion(pb.CompletionRequest(completion_id="many0"), timeout=1).status == "cancelling"
        assert list(streams[0]) == []
    finally:
        for stream in streams:
            stream.cancel()
        release.set()


@pytest.mark.asyncio
async def test_disconnect_before_first_iteration_removes_registration(manager, monkeypatch):
    callbacks = []

    class DisconnectedContext:
        def add_done_callback(self, callback):
            callbacks.append(callback)

        def done(self):
            return True

    async def events(**kwargs):
        raise AssertionError("首次迭代前断连不得启动 producer")
        yield

    monkeypatch.setattr(runtime_module, "stream_completion_events", events)
    output = [event async for event in qa_routes.create_chat_completion(request(), DisconnectedContext())]
    assert output == []
    assert manager.get_status("cmp_rpc") is None
    replacement = qa_routes.completion_manager.create(
        completion_id="cmp_rpc", workspace={"stub": True},
        messages=qa_routes._messages(request()),
    )
    try:
        callbacks[0](None)
        assert manager.get_status("cmp_rpc")["status"] == "in_progress"
    finally:
        replacement.close()


def test_chat_streams_typed_events_and_preserves_json(rpc, manager, monkeypatch):
    """事件按序逐条传输，动态 JSON 保留大整数、空值和特殊字符。"""
    payload = {"number": 2 ** 60 + 1, "text": '中文\n"引号"', "null": None}
    async def events(**kwargs):
        yield {"type": "model_message", "content": "回答", "is_final": False,
               "tool_call_count": 1, "tool_calls": [{"id": "call1", "name": "read", "args": payload}]}
        yield {"type": "tool_completed", "tool": "read", "tool_call_id": "call1",
               "args": payload, "result": payload}
        if False:
            yield {}
    monkeypatch.setattr(runtime_module, "stream_completion_events", events)
    result = list(rpc.ChatCompletion(request(), timeout=5))
    assert [e.seq for e in result] == [1, 2, 3, 4]
    assert result[0].type == "completion.created"
    result = result[1:]
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
        if False:
            yield {}
    monkeypatch.setattr(manager_module, "build_qa_model", build)
    monkeypatch.setattr(runtime_module, "stream_completion_events", events)
    history = [{"id": "a", "name": "read", "args": {"path": "a.md"}}]
    messages = [
        pb.QaMessage(role="assistant", content="", tool_calls_json=json.dumps(history)),
        pb.QaMessage(role="tool", content="结果", tool_call_id="a", name="read"),
    ]
    list(rpc.ChatCompletion(request(messages=messages, run_options=pb.RunOptions(tool_execution_timeout=0),
                                   model_config=pb.ModelConfig(top_k=0, temperature=0)), timeout=5))
    assert seen["messages"][0].tool_calls == history
    assert seen["messages"][1].tool_call_id == "a"
    assert seen["run_options"] == RunOptions(tool_execution_timeout=0)
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
                        lambda **kwargs: async_items([]))
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
    assert len(events) == 2
    assert events[0].type == "completion.created"
    assert events[-1].type == "completion.failed"
    assert events[-1].error_message == '失败\n"原因"'


def test_cancel_interrupts_tool_wait_without_waiting_for_thread(rpc, manager, monkeypatch):
    """取消 RPC 返回 cancelling，线程仍阻塞时原流即可发出唯一取消终态。"""
    release = threading.Event()
    started = threading.Event()
    async def events(**kwargs):
        yield {"type": "model_message", "tool_calls": [{"id": "call1", "name": "read", "args": {}}]}
        started.set()
        assert await asyncio.to_thread(release.wait, 5)
        yield {"type": "tool_completed", "tool": "read", "tool_call_id": "call1", "result": {"ok": True}}
        if False:
            yield {}
    monkeypatch.setattr(runtime_module, "stream_completion_events", events)
    stream = rpc.ChatCompletion(request(), timeout=8)
    try:
        assert next(stream).type == "completion.created"
        assert next(stream).type == "model_message"
        assert started.wait(2)
        cancel = rpc.CancelCompletion(pb.CompletionRequest(completion_id="cmp_rpc"), timeout=1)
        assert cancel.status == "cancelling"
        assert not release.is_set()
        remaining = list(stream)
        assert remaining == []
        assert not release.is_set()
    finally:
        release.set()
        stream.cancel()


@pytest.mark.parametrize("deadline", [False, True])
def test_transport_cancel_or_deadline_cleans_runtime(rpc, manager, monkeypatch, deadline):
    """RPC 取消和超时唤醒阻塞消费者并释放注册项，后台观察停止信号。"""
    release = threading.Event()
    stopped = threading.Event()
    async def events(**kwargs):
        if False:
            yield {}
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
        if False:
            yield {}
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
        assert list(stream) == []
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
