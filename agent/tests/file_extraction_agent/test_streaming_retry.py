"""真实 LangChain 回调进入图流 → 验证增量时序、固定配置重试和取消。"""

import asyncio
import random
from contextlib import aclosing

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessageChunk, HumanMessage
from langchain_core.outputs import ChatGenerationChunk
from pydantic import PrivateAttr

from service.file_extraction_agent.core import graph, model_invocation
from service.file_extraction_agent.completion_runtime import stream_completion_events
from service.file_extraction_agent.schemas import DocumentQaMessage


class StreamingModel(BaseChatModel):
    failures: int = 0
    _calls: int = PrivateAttr(default=0)
    _release: asyncio.Event = PrivateAttr(default_factory=asyncio.Event)
    _closed: asyncio.Event = PrivateAttr(default_factory=asyncio.Event)

    @property
    def _llm_type(self):
        return "test-stream"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, *args, **kwargs):
        raise AssertionError("不得切换到同步或非流式调用")

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        self._calls += 1
        try:
            yield ChatGenerationChunk(message=AIMessageChunk(content="前半"))
            if self._calls <= self.failures:
                raise ConnectionError("请求中断")
            await self._release.wait()
            yield ChatGenerationChunk(message=AIMessageChunk(
                content="后半", response_metadata={"finish_reason": "stop"},
            ))
        finally:
            self._closed.set()


async def test_native_messages_arrive_before_model_finishes(resource_path):
    model = StreamingModel()
    async with aclosing(stream_completion_events(
        resource_path=resource_path, messages=[DocumentQaMessage(role="user", content="问题")],
        qa_model=model,
    )) as events:
        received = []
        while not any(e["type"] == "model_message.delta" for e in received):
            received.append(await asyncio.wait_for(anext(events), 2))
        assert not model._closed.is_set()
        assert received[-1]["delta"] == "前半"
        model._release.set()
        received.extend([e async for e in events])
    done = [e for e in received if e["type"] == "model_message.done"]
    assert len(done) == 1 and done[0]["content"] == "前半后半"
    message_events = [e for e in received if e["type"].startswith("model_message.")]
    assert message_events[0]["type"] == "model_message.started"
    assert len({e["message_id"] for e in message_events}) == 1
    assert "".join(e["delta"] for e in message_events if "delta" in e) == "前半后半"


async def test_graph_retries_same_model_five_times_and_reports_before_wait(resource_path, monkeypatch):
    monkeypatch.setattr(random, "random", lambda: 0.5)
    model = StreamingModel(failures=5)
    waits = []
    release = asyncio.Event()

    async def wait_retry(delay):
        waits.append(delay)
        await release.wait()

    monkeypatch.setattr(graph, "_wait_retry", wait_retry, raising=False)
    async with aclosing(stream_completion_events(
        resource_path=resource_path, messages=[DocumentQaMessage(role="user", content="问题")],
        qa_model=model,
    )) as events:
        received = []
        while not any(e["type"] == "model_request.retrying" for e in received):
            received.append(await asyncio.wait_for(anext(events), 2))
        assert model._calls == 1
        assert received[-1]["attempt"] == 2
        release.set()
        received.extend([e async for e in events])
    assert model._calls == 5
    assert waits == [0.4375, 0.875, 1.75, 3.5]
    retries = [e for e in received if e["type"] == "model_request.retrying"]
    assert [e["retry_delay_ms"] for e in retries] == [round(delay * 1000) for delay in waits]
    assert len([e for e in received if e["type"] == "model_request.retrying"]) == 4
    starts = [e["message_id"] for e in received if e["type"] == "model_message.started"]
    assert len(starts) == len(set(starts)) == 5
    assert not any(e["type"] == "model_message.done" for e in received)
    assert received[-1]["type"] == "completion.failed"


@pytest.mark.parametrize("headers, expected", [
    ({"retry-after-ms": "1250", "retry-after": "10"}, 1.25),
    ({"retry-after": "30"}, 30.0),
    ({"retry-after": "120"}, 120.0),
    ({"retry-after-ms": "bad", "retry-after": "2.5"}, 2.5),
    ({"retry-after": "Wed, 09 Sep 2026 00:00:30 GMT"}, 30.0),
    ({"retry-after": "121"}, None),
    ({"retry-after": "0"}, None),
    ({"retry-after": "-1"}, None),
    ({"retry-after": "nan"}, None),
    ({"retry-after": "inf"}, None),
    ({"retry-after": "invalid"}, None),
    ({}, None),
])
async def test_model_failure_preserves_valid_retry_after(headers, expected, monkeypatch):
    import time
    import httpx
    from openai import RateLimitError

    monkeypatch.setattr(time, "time", lambda: 1788912000.0)
    response = httpx.Response(429, headers=headers, request=httpx.Request("POST", "https://model.invalid"))

    class LimitedModel:
        async def astream(self, messages):
            raise RateLimitError("限流", response=response, body=None)
            yield

    result = await model_invocation._invoke_model_message(LimitedModel(), [])
    assert result.retry_after_seconds == expected


def test_retry_backoff_caps_base_and_honors_server_delay(monkeypatch):
    from service.file_extraction_agent.core.contracts import ModelCallFailure

    monkeypatch.setattr(random, "random", lambda: 0.5)
    assert graph._retry_delay(20, ModelCallFailure("失败")) == 7.0
    assert graph._retry_delay(1, ModelCallFailure("限流", retry_after_seconds=30)) == 30


async def test_server_retry_delay_reaches_event_and_wait(resource_path, monkeypatch):
    import httpx
    from openai import RateLimitError

    class LimitedModel(StreamingModel):
        async def _astream(self, messages, **kwargs):
            self._calls += 1
            response = httpx.Response(429, headers={"Retry-After": "30"},
                                      request=httpx.Request("POST", "https://model.invalid"))
            raise RateLimitError("限流", response=response, body=None)
            yield

    waits = []

    async def wait_retry(delay):
        waits.append(delay)

    monkeypatch.setattr(graph, "_wait_retry", wait_retry)
    model = LimitedModel()
    events = [e async for e in stream_completion_events(
        resource_path=resource_path, messages=[DocumentQaMessage(role="user", content="问题")], qa_model=model,
    )]
    assert model._calls == 5 and waits == [30.0] * 4
    assert [e["retry_delay_ms"] for e in events if e["type"] == "model_request.retrying"] == [30000] * 4
    assert events[-1]["type"] == "completion.failed"


async def test_single_model_call_returns_failure_without_retry():
    model = StreamingModel(failures=5)
    result = await model_invocation._invoke_model_message(model, [HumanMessage(content="问题")])
    assert type(result).__name__ == "ModelCallFailure"
    assert model._calls == 1


async def test_cancel_model_closes_stream_without_retry():
    model = StreamingModel()
    task = asyncio.create_task(model_invocation._invoke_model_message(model, []))
    while model._calls == 0:
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert model._closed.is_set()
    assert model._calls == 1


async def test_runtime_cancel_during_retry_wait_stops_next_attempt(resource_path, monkeypatch):
    from service.file_extraction_agent.completion_runtime import CompletionRuntime

    model = StreamingModel(failures=5)
    entered, closed = asyncio.Event(), asyncio.Event()

    async def wait_retry(delay):
        try:
            entered.set()
            await asyncio.Event().wait()
        finally:
            closed.set()

    monkeypatch.setattr(graph, "_wait_retry", wait_retry)
    runtime = CompletionRuntime(resource_path, model, [DocumentQaMessage(role="user", content="问题")])
    received = []

    async def consume():
        received.extend([e async for e in runtime.astream()])

    task = asyncio.create_task(consume())
    await asyncio.wait_for(entered.wait(), 2)
    runtime.terminate()
    await asyncio.wait_for(task, 2)
    assert closed.is_set() and model._calls == 1
    assert received[-1]["type"] == "completion.cancelled"
    assert sum(e["type"].startswith("completion.") and e["type"] != "completion.created" for e in received) == 1


async def test_retry_success_keeps_failed_partial_text_out_of_history(monkeypatch):
    model = StreamingModel(failures=4)
    model._release.set()
    monkeypatch.setattr(graph, "_wait_retry", lambda delay: asyncio.sleep(0))
    result = await graph.build_qa_graph(model, []).ainvoke({"messages": [HumanMessage(content="问题")]})
    assert model._calls == 5
    assert len(result["messages"]) == 2
    assert result["messages"][-1].content == "前半后半"
    assert result["model_attempt"] == 0 and result["model_failure"] is None


async def test_chatopenai_native_callback_and_http_stream_close():
    import json
    import httpx
    from langchain_openai import ChatOpenAI
    from service.file_extraction_agent.core.contracts import MessageDelta

    release, closed = asyncio.Event(), asyncio.Event()

    class ResponseBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            payload = {"id": "test-response", "object": "chat.completion.chunk", "created": 0,
                       "model": "test", "choices": [{"index": 0, "delta": {"content": "实时"}, "finish_reason": None}]}
            yield ("data: " + json.dumps(payload) + "\n\n").encode()
            await release.wait()

        async def aclose(self):
            closed.set()

    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=ResponseBody())
    )) as client:
        model = ChatOpenAI(model="test", api_key="test", base_url="https://model.invalid/v1",
                           http_async_client=client, max_retries=0, streaming=True)
        events = graph.stream_qa_graph(qa_model=model, tools=[], messages=[HumanMessage(content="问题")])
        async with aclosing(events):
            while True:
                event = await asyncio.wait_for(anext(events), 2)
                if isinstance(event, MessageDelta):
                    assert event.delta == "实时" and not closed.is_set()
                    break
            pending = asyncio.create_task(anext(events))
            await asyncio.sleep(0)
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
        assert closed.is_set()
