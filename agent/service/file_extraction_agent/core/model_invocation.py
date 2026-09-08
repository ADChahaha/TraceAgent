"""固定模型与历史 → 单次调用并聚合 → 校验 → 完整消息或失败结果。

重试和指数退避由图节点负责；取消传播并关闭 provider 流，不转成普通失败。
"""

from __future__ import annotations

from collections.abc import Sequence
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    BaseMessageChunk,
    message_chunk_to_message,
)

from service.file_extraction_agent.core.contracts import (
    BoundModel,
    ChatModel,
    ModelAttempts,
    ModelCallAttempt,
    ModelCallFailure,
)

from service.file_extraction_agent.core.messages import _validate_model_message

async def _invoke_model_message(model: BoundModel, messages: Sequence[BaseMessage]) -> AIMessage | ModelCallFailure:
    attempt = _model_call_attempts(model)[0]
    try:
        response = (
            await _stream_model_message(attempt.model, messages)
            if attempt.use_stream else await attempt.model.ainvoke(messages)
        )
        if not isinstance(response, AIMessage):
            raise TypeError("model must return an AIMessage")
        _validate_model_message(response)
        return response
    except Exception as exc:
        return ModelCallFailure(error=f"{type(exc).__name__}: {exc}")


def _model_call_attempts(model: BoundModel) -> list[ModelCallAttempt]:
    if isinstance(model, ModelAttempts):
        attempts = model.model_call_attempts()
        if len(attempts) != 1:
            raise ValueError("exactly one fixed model configuration is required")
        return attempts
    return [ModelCallAttempt("stream", model, True)]


async def _stream_model_message(model: ChatModel, messages: Sequence[BaseMessage]) -> AIMessage:
    streamed_message: BaseMessageChunk | None = None
    chunks = model.astream(messages)
    try:
        async for chunk in chunks:
            streamed_message = chunk if streamed_message is None else streamed_message + chunk
    finally:
        close = getattr(chunks, "aclose", None)
        if close is not None:
            await close()
    if streamed_message is None:
        raise RuntimeError("model stream returned no chunks")
    message = message_chunk_to_message(streamed_message)
    if not isinstance(message, AIMessage):
        raise TypeError("model stream must return AIMessage chunks")
    return message
