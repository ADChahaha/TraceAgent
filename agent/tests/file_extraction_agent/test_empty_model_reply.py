from unittest.mock import AsyncMock, Mock

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage

from service.file_extraction_agent.core import graph
from service.file_extraction_agent.core.contracts import ModelCallFailure
from service.file_extraction_agent.core.model import ConfiguredChatModel
from service.file_extraction_agent.core.model_invocation import _invoke_model_message


@pytest.mark.parametrize("content", ["", " \n\t", [{"type": "text", "text": " "}], [{"type": "reasoning", "reasoning": "hidden"}]])
async def test_empty_terminal_reply_is_a_retryable_failure(content):
    class Provider:
        async def astream(self, messages):
            yield AIMessageChunk(content=content, response_metadata={"finish_reason": "stop"})

    result = await _invoke_model_message(Provider(), [HumanMessage(content="Question")])
    assert isinstance(result, ModelCallFailure)
    assert "empty visible content" in result.error


async def test_empty_reply_is_not_added_to_retry_history(monkeypatch):
    monkeypatch.setattr(graph, "_wait_retry", AsyncMock())
    provider = Mock(spec=["bind_tools", "ainvoke"])
    provider.bind_tools.return_value = provider
    provider.ainvoke = AsyncMock(side_effect=[
        AIMessage(content=" ", response_metadata={"finish_reason": "stop"}),
        AIMessage(content="The budget is $48,000.", response_metadata={"finish_reason": "stop"}),
    ])
    compiled = graph.build_qa_graph(ConfiguredChatModel(provider, use_stream=False), [])
    result = await compiled.ainvoke({"messages": [HumanMessage(content="Budget?")]})
    assert provider.ainvoke.await_count == 2
    assert [message.content for message in result["messages"]] == ["Budget?", "The budget is $48,000."]
    assert all(message.content.strip() for message in provider.ainvoke.call_args.args[0])
