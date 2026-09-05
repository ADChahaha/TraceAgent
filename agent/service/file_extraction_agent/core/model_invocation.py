"""模型与消息 → 按顺序尝试 stream/invoke → 聚合并校验响应 → 返回完整 AIMessage。

调用失败或响应不完整时按随机指数退避重试，最多五次；全部失败抛 RuntimeError，
附带各次错误。消息转换与终止信号校验由 messages.py 负责。
"""

from __future__ import annotations

import random
import time
from typing import Any

from langchain_core.messages import message_chunk_to_message

from service.file_extraction_agent.core.messages import _validate_model_message

PROVIDER_ATTEMPT_LIMIT = 5
PROVIDER_BACKOFF_SLOT_SECONDS = 0.25


def _invoke_model_message(model: Any, messages: list[Any]) -> Any:
    errors: list[tuple[str, Exception]] = []
    attempts = _model_call_attempts(model)[:PROVIDER_ATTEMPT_LIMIT]
    for attempt_index, attempt in enumerate(attempts):
        attempt_name = _read(attempt, "name", "model_call")
        attempt_model = _read(attempt, "model", model)
        use_stream = bool(_read(attempt, "use_stream", True))
        try:
            if use_stream:
                message = _stream_model_message(attempt_model, messages)
            else:
                message = attempt_model.invoke(messages)
            _validate_model_message(message)
            return message
        except Exception as exc:
            errors.append((str(attempt_name), exc))
            if attempt_index < len(attempts) - 1:
                _sleep_before_next_provider_attempt(attempt_index)
    details = "; ".join(f"{name}: {type(error).__name__}: {error}" for name, error in errors)
    raise RuntimeError(f"all model call attempts failed: {details}")



def _model_call_attempts(model: Any) -> list[Any]:
    attempts = getattr(model, "model_call_attempts", None)
    if callable(attempts):
        return list(attempts())
    return [
        {"name": "stream", "model": model, "use_stream": True},
        {"name": "invoke", "model": model, "use_stream": False},
    ]



def _sleep_before_next_provider_attempt(attempt_index: int) -> None:
    if attempt_index >= PROVIDER_ATTEMPT_LIMIT - 1:
        return
    upper_slot = (2 ** max(0, attempt_index + 1)) - 1
    slot_count = random.randint(0, upper_slot)
    delay = slot_count * PROVIDER_BACKOFF_SLOT_SECONDS
    if delay > 0:
        time.sleep(delay)



def _stream_model_message(model: Any, messages: list[Any]) -> Any:
    stream = getattr(model, "stream", None)
    if not callable(stream):
        raise RuntimeError("model does not support stream")
    streamed_message: Any = None
    for chunk in stream(messages):
        streamed_message = chunk if streamed_message is None else streamed_message + chunk
    if streamed_message is None:
        raise RuntimeError("model stream returned no chunks")
    return message_chunk_to_message(streamed_message)



def _read(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)
