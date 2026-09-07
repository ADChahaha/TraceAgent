"""真实异步图链路 → 模型与工具协程 → 批次事件与取消清理。"""

import asyncio
import threading

from langchain_core.messages import AIMessageChunk

from service.file_extraction_agent.core import executor, loop, model_invocation
from service.file_extraction_agent.completion_runtime import CompletionRuntime
from service.file_extraction_agent.schemas import DocumentQaMessage


def test_runtime_executes_model_and_tools_on_event_loop(resource_path, monkeypatch):
    async def run():
        owner = threading.get_ident()
        calls = []

        class Model:
            def bind_tools(self, tools):
                return self

            async def astream(self, messages):
                assert threading.get_ident() == owner
                calls.append("model")
                await asyncio.sleep(0)
                if len(calls) == 1:
                    yield AIMessageChunk(content="读取", tool_call_chunks=[
                        {"id": "a", "name": "read", "args": "{}", "index": 0}])
                else:
                    yield AIMessageChunk(content="答案", response_metadata={"finish_reason": "stop"})

        class Tool:
            name = "read"

            async def ainvoke(self, args):
                assert threading.get_ident() == owner
                calls.append("tool")
                await asyncio.sleep(0)
                return {"ok": True}

        monkeypatch.setattr(loop, "build_tools", lambda workspace: [Tool()])
        runtime = CompletionRuntime(resource_path, Model(), [DocumentQaMessage(role="user", content="问题")])
        events = [event async for event in runtime.astream()]
        assert calls == ["model", "tool", "model"]
        assert events[-1]["type"] == "completion.completed"
        assert [e["seq"] for e in events] == list(range(1, len(events) + 1))

    asyncio.run(run())


def test_model_cancellation_closes_provider_stream():
    async def run():
        started, closed = asyncio.Event(), asyncio.Event()

        class Model:
            async def astream(self, messages):
                try:
                    started.set()
                    await asyncio.Event().wait()
                    yield AIMessageChunk(content="迟到")
                finally:
                    closed.set()

        task = asyncio.create_task(model_invocation._invoke_model_message(Model(), []))
        await asyncio.wait_for(started.wait(), 1)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        assert closed.is_set()

    asyncio.run(run())


def test_async_tools_share_deadline_preserve_order_and_cancel_pending():
    async def run():
        started, closed = asyncio.Event(), asyncio.Event()

        class Tool:
            name = "read"

            async def ainvoke(self, args):
                if args["slow"]:
                    try:
                        started.set()
                        await asyncio.Event().wait()
                    finally:
                        closed.set()
                await started.wait()
                return {"ok": True}

        calls = [{"id": "slow", "name": "read", "args": {"slow": True}},
                 {"id": "fast", "name": "read", "args": {"slow": False}}]
        results = await executor._execute_tools_parallel(calls, [Tool()], timeout=0.05)
        assert [r.tool_call_id for r in results] == ["slow", "fast"]
        assert [r.status for r in results] == ["error", "success"]
        assert closed.is_set()

    asyncio.run(run())
