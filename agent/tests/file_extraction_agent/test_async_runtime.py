"""多个请求内事件流异步等待，不占用阻塞执行器。"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import pytest
from service.file_extraction_agent import completion_runtime as module

async def test_waiting_streams_leave_executor_free_and_cancel_cleanly(monkeypatch):
    entered, cleaned = [], []
    async def events(**kwargs):
        entered.append(1)
        try:
            await asyncio.Event().wait()
            yield {}
        finally:
            cleaned.append(1)
    monkeypatch.setattr(module, "stream_completion_events", events)
    asyncio.get_running_loop().set_default_executor(ThreadPoolExecutor(max_workers=1))
    async def consume():
        return [e async for e in module.stream_completion({}, object(), [])]
    tasks = [asyncio.create_task(consume()) for _ in range(4)]
    try:
        await asyncio.sleep(0)
        assert len(entered) == 4
        assert await asyncio.wait_for(asyncio.to_thread(lambda: "free"), 1) == "free"
        tasks[0].cancel()
        with pytest.raises(asyncio.CancelledError):
            await tasks[0]
        assert len(cleaned) == 1
        assert all(not t.done() for t in tasks[1:])
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    assert len(cleaned) == 4
