"""异步消费真实运行时，验证等待不占执行器、FIFO 与取消清理。"""

from tests.async_helpers import async_items
import asyncio
from concurrent.futures import ThreadPoolExecutor

import pytest

from service.file_extraction_agent import completion_runtime as runtime_module
from service.file_extraction_agent import manager as manager_module
from service.file_extraction_agent.manager import CompletionManager
from service.file_extraction_agent.schemas import DocumentQaMessage


@pytest.mark.parametrize("ending", ["completed", "failed", "cancelled"])
def test_async_stream_preserves_events_and_cleanup(resource_path, monkeypatch, ending):
    monkeypatch.setattr(manager_module, "build_qa_model", lambda config: object())
    async def source(**kwargs):
        yield {"type": "model_message", "content": "答案"}
        if ending == "failed":
            raise RuntimeError("失败")
        if ending == "cancelled":
            manager.terminate("async")
    monkeypatch.setattr(runtime_module, "stream_completion_events", source)
    manager = CompletionManager()
    stream = manager.create(completion_id="async", resource_path=resource_path,
                            messages=[DocumentQaMessage(role="user", content="问题")]).stream()

    async def consume():
        return [event async for event in stream]

    events = asyncio.run(consume())
    assert [event["seq"] for event in events] == list(range(1, len(events) + 1))
    if ending == "cancelled":
        assert not any(e["type"] == "completion.cancelled" for e in events)
    else:
        assert events[-1]["status"] == ending
    assert manager.get_status("async") is None


def test_waiting_streams_leave_executor_free_and_cancel_cleanly(resource_path, monkeypatch):
    release = asyncio.Event()

    async def events(**kw):
        await release.wait()
        if False:
            yield {}

    monkeypatch.setattr(manager_module, "build_qa_model", lambda config: object())
    monkeypatch.setattr(runtime_module, "stream_completion_events", events)
    manager = CompletionManager()

    async def run():
        asyncio.get_running_loop().set_default_executor(ThreadPoolExecutor(max_workers=1))
        streams = [manager.create(completion_id=f"async{i}", resource_path=resource_path,
                   messages=[DocumentQaMessage(role="user", content="问题")]).stream() for i in range(4)]
        tasks = []
        try:
            await asyncio.wait_for(asyncio.gather(*(anext(s) for s in streams)), 2)
            tasks = [asyncio.create_task(anext(s)) for s in streams]
            await asyncio.sleep(0.05)
            assert await asyncio.wait_for(asyncio.to_thread(lambda: "free"), 1) == "free"
            assert manager.terminate("async0")["status"] == "cancelling"
            with pytest.raises(StopAsyncIteration):
                await asyncio.wait_for(tasks[0], 1)
            for task in tasks[1:]:
                task.cancel()
            await asyncio.gather(*tasks[1:], return_exceptions=True)
        finally:
            release.set()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            for stream in streams:
                await stream.aclose()
        assert not manager._completions

    asyncio.run(run())
