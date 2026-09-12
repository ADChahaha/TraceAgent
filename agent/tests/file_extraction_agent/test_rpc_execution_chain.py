"""调用方直接驱动事件生成，取消沿当前 Task 传播并等待清理。"""

import asyncio

import pytest

from service.file_extraction_agent import turn_stream as module


async def test_execution_stays_in_consuming_task(monkeypatch):
    owner = asyncio.current_task()
    advanced = []

    async def events(**kwargs):
        assert asyncio.current_task() is owner
        advanced.append(1)
        yield {"type": "model_message.delta", "delta": "正文"}
        advanced.append(2)

    monkeypatch.setattr(module, "stream_completion_events", events)
    runtime = module.stream_completion({}, object(), [])
    stream = runtime
    try:
        assert (await anext(stream))["type"] == "completion.created"
        await asyncio.sleep(0)
        assert advanced == []
        assert (await anext(stream))["delta"] == "正文"
        await asyncio.sleep(0)
        assert advanced == [1]
    finally:
        await stream.aclose()


async def test_consumer_cancellation_waits_for_inner_cleanup(monkeypatch):
    started, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    received = []

    async def events(**kwargs):
        try:
            started.set()
            await asyncio.Event().wait()
            yield {}
        finally:
            cleaning.set()
            await release.wait()

    monkeypatch.setattr(module, "stream_completion_events", events)
    async def consume():
        async for event in module.stream_completion({}, object(), []):
            received.append(event)

    task = asyncio.create_task(consume())
    await asyncio.wait_for(started.wait(), 1)
    task.cancel()
    try:
        await asyncio.wait_for(cleaning.wait(), 1)
        assert not task.done()
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
    assert [e["type"] for e in received] == ["completion.created"]
