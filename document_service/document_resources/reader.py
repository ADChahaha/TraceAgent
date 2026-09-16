"""从会话文档归档中读取段落块文本：供前端回溯引用。"""

from __future__ import annotations

import io
import zipfile
from typing import Any

from traceagent_shared.object_store import build_s3_object_store

DOCUMENT_ARCHIVE_KEY = "documents.zip"


class ArchiveNotFoundError(ValueError):
    """会话桶内不存在文档归档。"""


def read_blocks(bucket: str, keys: list[str]) -> list[dict[str, object]]:
    """按 key 精确匹配归档成员并解码文本；缺失 key 返回 found=false、text 为空。"""
    if not bucket:
        raise ValueError("bucket is required")
    if not keys:
        raise ValueError("keys are required")
    store = build_s3_object_store()
    try:
        archive = store.get_object(bucket, DOCUMENT_ARCHIVE_KEY)
    except Exception as exc:
        # 桶缺失或存储异常在引用回溯场景下统一表现为"该会话没有可用归档"。
        raise ArchiveNotFoundError(f"missing document archive for bucket: {bucket}") from exc
    if archive is None:
        raise ArchiveNotFoundError(f"missing document archive for bucket: {bucket}")
    blocks: list[dict[str, object]] = []
    with zipfile.ZipFile(io.BytesIO(archive)) as archive_file:
        members = set(archive_file.namelist())
        for key in keys:
            found = key in members
            blocks.append({"key": key, "text": archive_file.read(key).decode("utf-8") if found else "", "found": found})
    return blocks


__all__ = ["ArchiveNotFoundError", "read_blocks"]
