"""单一模型配置与统一文本提取 → 验证清理后的实际输入输出。"""

import pytest
from langchain_core.messages import AIMessage

from service.file_extraction_agent.core import model, messages
from service.file_extraction_agent.core.model_invocation import _invoke_model_message
from service.file_extraction_agent.schemas import ModelConfig


async def test_single_model_binding_preserves_invoke_mode():
    class Provider:
        def bind_tools(self, tools):
            self.tools = tools
            return self

        async def ainvoke(self, history):
            return AIMessage(content="回答", response_metadata={"finish_reason": "stop"})

    provider = Provider()
    configured = model.ConfiguredChatModel(provider, use_stream=False)
    bound = configured.bind_tools([])
    assert bound.model is provider and bound.use_stream is False
    assert (await _invoke_model_message(bound, [])).content == "回答"


def test_deepseek_uses_standard_model_without_custom_thinking(monkeypatch):
    captured = []
    class ChatModel:
        def __init__(self, **kwargs):
            captured.append(kwargs)

    monkeypatch.setattr(model, "_chat_model_class", lambda: ChatModel)
    result = model.build_chat_model(ModelConfig(
        base_url="https://api.deepseek.com/v1", api_key="test", model_name="deepseek-chat",
        api_transport="chat_completions", reasoning_effort="high", top_k=5,
    ), "deepseek-chat")
    assert isinstance(result.model, ChatModel)
    assert captured[0]["extra_body"] == {"top_k": 5}
    assert captured[0]["reasoning_effort"] == "high"
    assert captured[0]["streaming"] is True
    assert captured[0]["max_retries"] == 0


@pytest.mark.parametrize("content, expected", [
    ("正文", "正文"),
    (["前", {"type": "text", "text": "后"}, {"type": "reasoning", "text": "隐藏"}], "前后"),
    ([{"type": "text"}, {"type": "text", "text": None}, {"type": "text", "text": 1}], ""),
    (None, ""),
])
def test_visible_text_ignores_non_text_and_invalid_blocks(content, expected):
    assert messages.visible_text(content) == expected
