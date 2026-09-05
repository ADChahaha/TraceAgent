"""路径输入 → 图内初始化 → 完整工具批次及取消边界。"""

from types import SimpleNamespace
from unittest.mock import Mock

from langchain_core.messages import AIMessage, ToolMessage

from service.file_extraction_agent.core import loop
from service.file_extraction_agent.core.model import ChatModelFallbackChain, ModelCallAttempt
from service.file_extraction_agent.schemas import DocumentQaMessage, RunOptions


def test_path_graph_returns_complete_tool_batch_and_stops_after_cancel(monkeypatch):
    state = SimpleNamespace(messages=[DocumentQaMessage(role="user", content="问题")], run_options=RunOptions())
    received = []

    def initialize(**kwargs):
        received.append(kwargs)
        return state

    monkeypatch.setattr(loop, "build_graph_state", initialize, raising=False)

    class Tool:
        name = "read"

        def invoke(self, args):
            if args["path"] == "bad":
                raise ValueError("invalid file")
            return "正文"

    monkeypatch.setattr(loop, "build_tools", lambda state: [Tool()])
    provider = Mock(spec=["bind_tools", "invoke"])
    provider.bind_tools.return_value = provider
    provider.invoke.return_value = AIMessage(content="读取", tool_calls=[
        {"id": "a", "name": "read", "args": {"path": "good"}},
        {"id": "b", "name": "read", "args": {"path": "bad"}},
    ])
    cancelled = False
    stream = loop.run_resolution_stream(
        resource_path="R", messages=state.messages, run_options=state.run_options,
        resolution_model=ChatModelFallbackChain([ModelCallAttempt("test", provider, False)]),
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
    assert set(received[0]) == {"resource_path", "messages", "run_options"}
