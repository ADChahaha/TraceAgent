"""会话标题生成：按用户首问与文件名调用轻量模型并清洗为简洁纯文本标题。

复用 `config.toml` 的 `[title_model]`（未配置字段回退 `[model]`），使用流式响应收集
可见文本以兼容仅支持流式的上游网关。空输入抛 ValueError，空输出抛 RuntimeError。
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from contextlib import aclosing
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from service.file_extraction_agent.core.messages import visible_text
from service.file_extraction_agent.core.model import (
    ConfiguredChatModel,
    build_chat_model,
    load_title_model_config,
)
from service.file_extraction_agent.schemas import ModelConfig

MAX_TITLE_LENGTH = 60
MAX_QUESTION_INPUT_LENGTH = 1000
MAX_FILENAME_HINTS = 5

_PREFIX_RE = re.compile(
    r"^(?:[#>*\-•]+\s*|(?:title|session\s+title|标题|会话标题)\s*[:：]\s*)+",
    re.IGNORECASE,
)
_WRAPPING_PAIRS = (
    ('"', '"'),
    ("'", "'"),
    ("`", "`"),
    ("“", "”"),
    ("‘", "’"),
    ("「", "」"),
    ("『", "』"),
    ("《", "》"),
    ("**", "**"),
    ("__", "__"),
)


def _strip_wrapping_pairs(text: str) -> str:
    """仅剥离首尾成对包裹的引号、书名号或 Markdown 强调符，避免破坏内部配对符号。"""
    changed = True
    while changed and text:
        changed = False
        for left, right in _WRAPPING_PAIRS:
            if len(text) >= len(left) + len(right) and text.startswith(left) and text.endswith(right):
                text = text[len(left) : len(text) - len(right)].strip()
                changed = True
    return text


def sanitize_title(raw: str, *, max_length: int = MAX_TITLE_LENGTH) -> str:
    """将模型原始输出清洗为单行、无引号与 Markdown 装饰的安全长度标题。"""
    if not isinstance(raw, str):
        return ""
    line = ""
    for candidate in raw.splitlines():
        cleaned = candidate.strip()
        if cleaned:
            line = cleaned
            break
    if not line:
        return ""

    text = _PREFIX_RE.sub("", line).strip()
    text = text.replace("**", "").replace("__", "").replace("`", "")
    text = _strip_wrapping_pairs(text)
    text = re.sub(r"\s+", " ", text).strip()
    text = text.rstrip("。.!！:：;；").strip()
    text = _strip_wrapping_pairs(text)
    text = text.rstrip("。.!！:：;；").strip()
    if len(text) > max_length:
        truncated = text[:max_length].rstrip()
        if " " in truncated and len(truncated.rsplit(" ", 1)[0]) >= max_length // 2:
            truncated = truncated.rsplit(" ", 1)[0].rstrip(" ,;:-")
        text = truncated
    return text.strip()


def build_title_messages(question: str, filenames: Sequence[str] = ()) -> list[BaseMessage]:
    """构造领域无关的会话标题总结提示消息。"""
    clipped_question = question.strip()[:MAX_QUESTION_INPUT_LENGTH]
    cleaned_files = [name.strip() for name in filenames if isinstance(name, str) and name.strip()][:MAX_FILENAME_HINTS]

    system_prompt = (
        "Generate a concise workspace title summarizing the user's opening question. "
        "Use the same language as the user's question. "
        "Keep it brief (about 4 to 8 words in English, or up to 18 characters in CJK). "
        "Output only the plain title text with no quotes, markdown, labels, or trailing punctuation."
    )
    user_lines = [f"Question: {clipped_question}"]
    if cleaned_files:
        user_lines.append("Documents: " + ", ".join(cleaned_files))
    return [
        SystemMessage(content=system_prompt),
        HumanMessage(content="\n".join(user_lines)),
    ]


async def generate_title(
    *,
    question: str,
    filenames: Sequence[str] = (),
    model_config: ModelConfig | None = None,
    chat_model: Any | None = None,
) -> str:
    """调用标题模型生成并清洗会话标题。"""
    normalized_question = (question or "").strip()
    if not normalized_question:
        raise ValueError("question must not be empty")

    if chat_model is None:
        config = model_config if model_config is not None else load_title_model_config()
        chat_model = build_chat_model(config, config.model_name)

    runnable = chat_model.model if isinstance(chat_model, ConfiguredChatModel) else chat_model
    messages = build_title_messages(normalized_question, filenames)

    if hasattr(runnable, "astream"):
        parts: list[str] = []
        async with aclosing(runnable.astream(messages)) as stream:
            async for chunk in stream:
                chunk_text = visible_text(getattr(chunk, "content", ""))
                if chunk_text:
                    parts.append(chunk_text)
        raw_text = "".join(parts)
    else:
        response = await runnable.ainvoke(messages)
        raw_text = visible_text(getattr(response, "content", response))

    title = sanitize_title(raw_text)
    if not title:
        raise RuntimeError("title model returned empty output")
    return title
