"""延迟加载的 OpenAI ChatModel 变体：只有真正需要 DeepSeek 思考链时才导入。"""

from __future__ import annotations

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatResult
from langchain_openai import ChatOpenAI
from openai import BaseModel as OpenAIModel


class DeepSeekReasoningChatOpenAI(ChatOpenAI):
    """响应中保存 DeepSeek reasoning_content，再随工具调用历史传回模型。"""

    def _create_chat_result(
        self,
        response: dict[str, object] | OpenAIModel,
        generation_info: dict[str, object] | None = None,
    ) -> ChatResult:
        result = super()._create_chat_result(response, generation_info)
        response_dict = response if isinstance(response, dict) else response.model_dump()
        choices = response_dict.get("choices") or []
        if not isinstance(choices, list):
            raise TypeError("model response choices must be a list")
        for generation, choice in zip(result.generations, choices, strict=False):
            message = choice.get("message") or {}
            reasoning_content = message.get("reasoning_content")
            if reasoning_content and isinstance(generation.message, AIMessage):
                generation.message.additional_kwargs["reasoning_content"] = reasoning_content
        return result

    def _get_request_payload(
        self,
        input_: LanguageModelInput,
        *,
        stop: list[str] | None = None,
        **kwargs: object,
    ) -> dict[str, object]:
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        messages = self._convert_input(input_).to_messages()
        for payload_message, source_message in zip(
            payload.get("messages", []),
            messages,
            strict=False,
        ):
            if isinstance(source_message, AIMessage):
                reasoning_content = source_message.additional_kwargs.get("reasoning_content")
                if reasoning_content:
                    payload_message["reasoning_content"] = reasoning_content
        return payload


__all__ = ["DeepSeekReasoningChatOpenAI"]
