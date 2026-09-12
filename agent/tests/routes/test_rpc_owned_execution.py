"""真实 RPC → 请求内执行 → 客户端取消后清理，调用之间不共享 ID 注册表。"""

import asyncio
import threading

import grpc
import pytest

from agent_proto import agent_pb2 as pb
from routes import file_extraction_agent as route
from service.file_extraction_agent import turn_stream as runtime


@pytest.fixture
def execution(monkeypatch):
    async def prepare(refs):
        return {"stub": True}

    monkeypatch.setattr(route, "prepare_workspace", prepare)
    monkeypatch.setattr(route, "build_qa_model", lambda config: object())


def request():
    return pb.ChatCompletionRequest(
        completion_id="same-id", messages=[pb.QaMessage(role="user", content="问题")])


def test_same_id_calls_are_independent(rpc, execution, monkeypatch):
    entered = [threading.Event(), threading.Event()]
    cleaned = [threading.Event(), threading.Event()]
    count = 0

    async def events(**kwargs):
        nonlocal count
        index = count
        count += 1
        try:
            entered[index].set()
            yield {"type": "model_message.delta", "delta": str(index)}
            await asyncio.Event().wait()
        finally:
            cleaned[index].set()

    monkeypatch.setattr(runtime, "stream_completion_events", events)
    first = rpc.ChatCompletion(request(), timeout=5)
    second = None
    try:
        assert next(first).type == "completion.created"
        assert entered[0].wait(2)
        second = rpc.ChatCompletion(request(), timeout=5)
        assert next(second).type == "completion.created"
        assert entered[1].wait(2)
        first.cancel()
        assert cleaned[0].wait(2)
        assert not cleaned[1].is_set()
        assert next(second).delta == "1"
    finally:
        first.cancel()
        if second is not None:
            second.cancel()


@pytest.mark.parametrize("ending", ["cancel", "deadline"])
def test_rpc_termination_cleans_awaiting_execution(rpc, execution, monkeypatch, ending):
    entered, cleaned = threading.Event(), threading.Event()

    async def events(**kwargs):
        try:
            entered.set()
            yield {"type": "model_message.delta", "delta": "正文"}
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0)
            cleaned.set()

    monkeypatch.setattr(runtime, "stream_completion_events", events)
    call = rpc.ChatCompletion(request(), timeout=0.5 if ending == "deadline" else 5)
    try:
        assert next(call).type == "completion.created"
        assert entered.wait(2)
        if ending == "cancel":
            # 不再消费任何事件，直接取消仍必须触发服务端清理。
            call.cancel()
        assert cleaned.wait(2)
    finally:
        call.cancel()


def test_removed_cancel_rpc_is_unimplemented(rpc_channel):
    assert "CancelCompletion" not in pb.DESCRIPTOR.services_by_name["AgentService"].methods_by_name
    call = rpc_channel.unary_unary("/traceagent.v1.AgentService/CancelCompletion")
    with pytest.raises(grpc.RpcError) as error:
        call(b"", timeout=2)
    assert error.value.code() == grpc.StatusCode.UNIMPLEMENTED


def test_cancel_during_prepare_cleans_before_any_event(rpc, monkeypatch):
    entered, cleaned = threading.Event(), threading.Event()

    async def prepare(refs):
        try:
            entered.set()
            await asyncio.Event().wait()
        finally:
            cleaned.set()

    monkeypatch.setattr(route, "prepare_workspace", prepare)
    call = rpc.ChatCompletion(request(), timeout=5)
    try:
        assert entered.wait(2)
        call.cancel()
        assert cleaned.wait(2)
    finally:
        call.cancel()


def test_cancel_closes_generator_while_transport_is_sending(rpc, execution, monkeypatch):
    entered, cleaned = threading.Event(), threading.Event()

    async def events(**kwargs):
        try:
            entered.set()
            while True:
                # 大事件使不再读取的客户端耗尽流控额度，取消不能依赖继续消费。
                yield {"type": "model_message.delta", "delta": "x" * (1024 * 1024)}
        finally:
            cleaned.set()

    monkeypatch.setattr(runtime, "stream_completion_events", events)
    call = rpc.ChatCompletion(request(), timeout=5)
    try:
        assert next(call).type == "completion.created"
        assert entered.wait(2)
        call.cancel()
        assert cleaned.wait(2)
    finally:
        call.cancel()
