"""workspace payload 绑定工具执行器 → 图内仅消息 → 完整批次及取消边界。"""

from unittest.mock import Mock, AsyncMock
from langchain_core.messages import AIMessage, ToolMessage
from service.file_extraction_agent.core import loop
from service.file_extraction_agent.core import executor
from service.file_extraction_agent.core.model import ConfiguredChatModel, ModelCallAttempt
from service.file_extraction_agent.schemas import DocumentQaMessage, RunOptions


async def test_workspace_graph_streams_tool_results_and_stops_after_cancel(monkeypatch):
    messages = [DocumentQaMessage(role="user", content="问题")]
    options = RunOptions(tool_execution_timeout=0.125)
    workspace = {"stub": True}
    received = []

    class Tool:
        name = "read"

        async def ainvoke(self, args):
            if args["path"] == "bad":
                raise ValueError("invalid file")
            return "正文"

    def bind_tools(context):
        received.append(context)
        return [Tool()]

    monkeypatch.setattr(loop, "build_tools", bind_tools)
    timeouts = []
    execute = executor._execute_tools_parallel

    async def execute_tools(*args, **kwargs):
        timeouts.append(kwargs["timeout"])
        return await execute(*args, **kwargs)

    monkeypatch.setattr(executor, "_execute_tools_parallel", execute_tools)
    provider = Mock(spec=["bind_tools", "ainvoke"])
    provider.bind_tools.return_value = provider
    provider.ainvoke = AsyncMock()
    provider.ainvoke.return_value = AIMessage(
        content="读取",
        tool_calls=[
            {"id": "a", "name": "read", "args": {"path": "good"}},
            {"id": "b", "name": "read", "args": {"path": "bad"}},
        ],
    )
    cancelled = False
    stream = loop.run_qa_stream(
        workspace=workspace,
        messages=messages,
        run_options=options,
        qa_model=ConfiguredChatModel([ModelCallAttempt("test", provider, False)]),
        should_stop=lambda: cancelled,
    )
    from service.file_extraction_agent.core.contracts import MessageStarted, MessageDelta
    assert isinstance(await anext(stream), MessageStarted)
    assert isinstance(await anext(stream), MessageDelta)
    assert isinstance(await anext(stream), AIMessage)
    batch = [await anext(stream), await anext(stream)]
    batch.sort(key=lambda result: result.tool_call_id)
    cancelled = True
    assert all((isinstance(result, ToolMessage) for result in batch))
    assert [(result.tool_call_id, result.name, result.status) for result in batch] == [
        ("a", "read", "success"),
        ("b", "read", "error"),
    ]
    assert batch[1].additional_kwargs["tool_args"] == {"path": "bad"}
    assert [item async for item in stream] == []
    assert provider.ainvoke.call_count == 1
    assert received == [workspace]
    assert timeouts == [0.125]
