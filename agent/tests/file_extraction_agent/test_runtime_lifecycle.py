"""producer 的返回/异常/取消 → astream 唯一完成出口与清理。"""

import asyncio

import pytest

from service.file_extraction_agent import completion_runtime as module
from service.file_extraction_agent.core.contracts import ModelFailed


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [False, True])
async def test_outer_stream_alone_emits_terminal(monkeypatch, failure):
    async def events(**kwargs):
        yield {"type": "model_message.delta", "delta": "正文"}
        if failure:
            raise RuntimeError("生成失败")
    monkeypatch.setattr(module, "stream_completion_events", events)
    runtime = module.CompletionRuntime([], object(), [])
    output = [event async for event in runtime.astream()]
    assert [event["type"] for event in output] == [
        "completion.created", "model_message.delta",
        "completion.failed" if failure else "completion.completed",
    ]
    assert [event["seq"] for event in output] == [1, 2, 3]
    if failure:
        assert output[-1]["error_message"] == "生成失败"


@pytest.mark.asyncio
async def test_cancel_closes_without_terminal_and_waits_for_cleanup(monkeypatch):
    started, cleaned = asyncio.Event(), asyncio.Event()
    callbacks = []
    async def events(**kwargs):
        try:
            started.set()
            await asyncio.Event().wait()
            yield {"type": "model_message.delta", "delta": "迟到"}
        finally:
            await asyncio.sleep(0)
            cleaned.set()
    monkeypatch.setattr(module, "stream_completion_events", events)
    runtime = module.CompletionRuntime([], object(), [], on_close=lambda: callbacks.append(1))
    async def consume():
        return [event async for event in runtime.astream()]
    consumer = asyncio.create_task(consume())
    await asyncio.wait_for(started.wait(), 1)
    await asyncio.to_thread(runtime.terminate)
    runtime.terminate()
    output = await asyncio.wait_for(consumer, 1)
    assert [event["type"] for event in output] == ["completion.created"]
    assert cleaned.is_set() and callbacks == [1]
    runtime.close()
    assert callbacks == [1]


@pytest.mark.asyncio
async def test_cancel_before_producer_starts_does_not_hang(monkeypatch):
    async def events(**kwargs):
        raise AssertionError("早取消不得运行 producer")
        yield
    monkeypatch.setattr(module, "stream_completion_events", events)
    runtime = module.CompletionRuntime([], object(), [])
    stream = runtime.astream()
    assert (await anext(stream))["type"] == "completion.created"
    runtime.terminate()
    assert [event async for event in stream] == []


@pytest.mark.asyncio
async def test_inner_failure_raises_without_completion_event(monkeypatch):
    async def outputs(**kwargs):
        yield ModelFailed("attempt-id", "请求耗尽")
    monkeypatch.setattr(module, "run_qa_stream", outputs)
    output = []
    with pytest.raises(RuntimeError, match="请求耗尽"):
        async for event in module.stream_completion_events(resource_path=[], messages=[], qa_model=object()):
            output.append(event)
    assert all(not event["type"].startswith("completion.") for event in output)


@pytest.mark.asyncio
@pytest.mark.parametrize("started", [False, True])
async def test_runtime_aclose_owns_stream_cleanup(monkeypatch, started):
    producing, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    callbacks = []

    async def events(**kwargs):
        try:
            producing.set()
            await asyncio.Event().wait()
            yield {}
        finally:
            cleaning.set()
            await release.wait()

    monkeypatch.setattr(module, "stream_completion_events", events)
    runtime = module.CompletionRuntime([], object(), [], on_close=lambda: callbacks.append(1))
    stream = runtime.stream()
    close_runtime = runtime.aclose
    if started:
        assert (await anext(stream))["type"] == "completion.created"
        await asyncio.wait_for(producing.wait(), 1)
    closing = asyncio.create_task(close_runtime())
    try:
        if started:
            await asyncio.wait_for(cleaning.wait(), 1)
            assert not closing.done()
            assert callbacks == []
    finally:
        release.set()
        await asyncio.wait_for(closing, 1)
    await runtime.aclose()
    assert callbacks == [1]
    assert [event async for event in stream] == []
    assert producing.is_set() == started
