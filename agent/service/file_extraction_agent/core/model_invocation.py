"""模型与消息 → 按顺序尝试 astream/ainvoke → 聚合并校验响应 → 返回完整 AIMessage。

调用失败或响应不完整时用 asyncio.sleep 随机指数退避，最多五次；全部失败抛 RuntimeError，
附带各次错误。消息转换与终止信号校验由 messages.py 负责。
"""

from __future__ import annotations

import asyncio
import random
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
)

from service.file_extraction_agent.core.messages import _validate_model_message

PROVIDER_ATTEMPT_LIMIT = 5
PROVIDER_BACKOFF_SLOT_SECONDS = 0.25


async def _invoke_model_message(model: BoundModel, messages: Sequence[BaseMessage]) -> AIMessage:
    errors: list[tuple[str, Exception]] = []
    attempts = _model_call_attempts(model)[:PROVIDER_ATTEMPT_LIMIT]
    for attempt_index, attempt in enumerate(attempts):
        try:
            response: BaseMessage
            if attempt.use_stream:
                response = await _stream_model_message(attempt.model, messages)
            else:
                response = await attempt.model.ainvoke(messages)
            if not isinstance(response, AIMessage):
                raise TypeError("model must return an AIMessage")
            _validate_model_message(response)
            return response
        except Exception as exc:
            errors.append((attempt.name, exc))
            if attempt_index < len(attempts) - 1:
                await _sleep_before_next_provider_attempt(attempt_index)
    details = "; ".join(f"{name}: {type(error).__name__}: {error}" for name, error in errors)
    raise RuntimeError(f"all model call attempts failed: {details}")


def _model_call_attempts(model: BoundModel) -> list[ModelCallAttempt]:
    if isinstance(model, ModelAttempts):
        return model.model_call_attempts()
    return [
        ModelCallAttempt("stream", model, True),
        ModelCallAttempt("invoke", model, False),
    ]


async def _sleep_before_next_provider_attempt(attempt_index: int) -> None:
    if attempt_index >= PROVIDER_ATTEMPT_LIMIT - 1:
        return
    upper_slot = (2 ** max(0, attempt_index + 1)) - 1
    slot_count = random.randint(0, upper_slot)
    delay = slot_count * PROVIDER_BACKOFF_SLOT_SECONDS
    if delay > 0:
        await asyncio.sleep(delay)


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
