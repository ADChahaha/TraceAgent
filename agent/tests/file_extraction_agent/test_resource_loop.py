"""路径初始化工具、配置绑定执行器 → 图内仅消息 → 完整批次及取消边界。"""

from unittest.mock import Mock

from langchain_core.messages import AIMessage, ToolMessage

from service.file_extraction_agent.core import loop
from service.file_extraction_agent.core import executor
from service.file_extraction_agent.core.model import ChatModelFallbackChain, ModelCallAttempt
from service.file_extraction_agent.schemas import DocumentQaMessage, RunOptions


def test_path_graph_returns_complete_tool_batch_and_stops_after_cancel(monkeypatch):
    messages = [DocumentQaMessage(role="user", content="问题")]
    options = RunOptions(tool_execution_timeout=0.125)
    workspace = object()
    received = []

    def initialize(path):
        received.append(path)
        return workspace

    monkeypatch.setattr(loop, "open_workspace", initialize)

    class Tool:
        name = "read"

        def invoke(self, args):
            if args["path"] == "bad":
                raise ValueError("invalid file")
            return "正文"

    def bind_tools(context):
        assert context is workspace
        return [Tool()]

    monkeypatch.setattr(loop, "build_tools", bind_tools)
    timeouts = []
    execute = executor._execute_tools_parallel

    def execute_tools(*args, **kwargs):
        timeouts.append(kwargs["timeout"])
        return execute(*args, **kwargs)

    monkeypatch.setattr(executor, "_execute_tools_parallel", execute_tools)
    provider = Mock(spec=["bind_tools", "invoke"])
    provider.bind_tools.return_value = provider
    provider.invoke.return_value = AIMessage(content="读取", tool_calls=[
        {"id": "a", "name": "read", "args": {"path": "good"}},
        {"id": "b", "name": "read", "args": {"path": "bad"}},
    ])
    cancelled = False
    stream = loop.run_qa_stream(
        resource_path="R", messages=messages, run_options=options,
        qa_model=ChatModelFallbackChain([ModelCallAttempt("test", provider, False)]),
        should_stop=lambda: cancelled,
    )
    assert isinstance(next(stream), AIMessage)
    cancelled = True
    batch = next(stream)
    assert isinstance(batch, list)
    assert all(isinstance(result, ToolMessage) for result in batch)
    assert [(result.tool_call_id, result.name, result.status) for result in batch] == [
        ("a", "read", "success"), ("b", "read", "error"),
    ]
    assert batch[1].additional_kwargs["tool_args"] == {"path": "bad"}
    assert list(stream) == []
    assert provider.invoke.call_count == 1
    assert received == ["R"]
    assert timeouts == [0.125]
