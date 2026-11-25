"""会话标题清洗与兜底派生工具，确保对外会话目录与恢复快照永不展示 UUID。"""

from __future__ import annotations

import re
from typing import Any

DEFAULT_SESSION_TITLE = "Untitled workspace"
MAX_SESSION_TITLE_LENGTH = 60
FALLBACK_QUESTION_MAX_LENGTH = 48

_WRAPPING_PAIRS = (
    ('"', '"'),
    ("'", "'"),
    ("`", "`"),
    ("“", "”"),
    ("‘", "’"),
    ("「", "」"),
    ("『", "』"),
    ("《", "》"),
)


def _strip_wrapping_pairs(text: str) -> str:
    """仅剥离首尾成对包装符，避免误削局部书名号或引号。"""
    changed = True
    while changed and text:
        changed = False
        for left, right in _WRAPPING_PAIRS:
            if len(text) >= len(left) + len(right) and text.startswith(left) and text.endswith(right):
                text = text[len(left) : len(text) - len(right)].strip()
                changed = True
    return text


def clean_session_title(raw: str | None, *, max_length: int = MAX_SESSION_TITLE_LENGTH) -> str:
    """将候选标题规范化为单行纯文本并截断到安全长度。"""
    if not isinstance(raw, str):
        return ""
    line = next((part.strip() for part in raw.splitlines() if part.strip()), "")
    if not line:
        return ""
    text = line.replace("**", "").replace("__", "").replace("`", "")
    text = re.sub(r"\s+", " ", text).strip()
    text = _strip_wrapping_pairs(text)
    text = text.rstrip("。.!！:：;；").strip()
    text = _strip_wrapping_pairs(text)
    text = text.rstrip("。.!！:：;；").strip()
    if len(text) > max_length:
        truncated = text[:max_length].rstrip()
        if " " in truncated and len(truncated.rsplit(" ", 1)[0]) >= max_length // 2:
            truncated = truncated.rsplit(" ", 1)[0].rstrip(" ,;:-")
        text = truncated
    return text.strip()


def filename_from_raw_location(location: str | None) -> str:
    """从 s3://<bucket>/raw/<filename> 提取可读文件名。"""
    if not isinstance(location, str) or not location.strip():
        return ""
    return location.rsplit("/", 1)[-1].strip()


def fallback_session_title(
    *,
    first_user_message: str | None = None,
    first_filename: str | None = None,
) -> str:
    """标题模型不可用或旧会话无标题时，依次按首条问题、首个文件名或默认标题降级。"""
    from_question = clean_session_title(first_user_message, max_length=FALLBACK_QUESTION_MAX_LENGTH)
    if from_question:
        return from_question
    from_file = clean_session_title(first_filename, max_length=FALLBACK_QUESTION_MAX_LENGTH)
    if from_file:
        return from_file
    return DEFAULT_SESSION_TITLE


def resolve_session_title(
    session: dict[str, Any],
    *,
    first_user_message: str | None = None,
    first_filename: str | None = None,
) -> str:
    """优先返回持久化标题，否则自动派生兜底标题。"""
    persisted = clean_session_title(session.get("title"))
    if persisted:
        return persisted
    return fallback_session_title(
        first_user_message=first_user_message,
        first_filename=first_filename,
    )
