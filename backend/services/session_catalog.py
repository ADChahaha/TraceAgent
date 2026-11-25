"""最近会话目录查询服务：隔离 routes 与 crud 层，统一补齐可读标题。"""

from __future__ import annotations

import asyncio
from typing import Any

from backend.crud import crud
from backend.services.protocols import DatabaseProtocol
from backend.services.session_title import filename_from_raw_location, resolve_session_title


async def list_recent_sessions(database: DatabaseProtocol, *, limit: int) -> list[dict[str, Any]]:
    """从持久化数据库列出最近会话，并为无标题旧会话按首条提问/文件名派生可读标题。"""

    def read() -> list[dict[str, Any]]:
        rows = crud.list_sessions_with_title_context(database.connect(), limit=limit)
        sessions: list[dict[str, Any]] = []
        for row in rows:
            first_user_message = row.pop("first_user_message", None)
            first_raw_location = row.pop("first_raw_location", None)
            row["title"] = resolve_session_title(
                row,
                first_user_message=first_user_message,
                first_filename=filename_from_raw_location(first_raw_location),
            )
            sessions.append(row)
        return sessions

    return await asyncio.to_thread(read)
