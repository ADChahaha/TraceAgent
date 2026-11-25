"""会话标题异步总结、参数校验与故障收口辅助任务。"""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Awaitable, Callable
from typing import Any

from backend.crud import crud
from backend.services.errors import ValidationError
from backend.services.protocols import AgentGateway, DatabaseProtocol
from backend.services.session_title import clean_session_title, fallback_session_title, filename_from_raw_location
from backend.services.time_utils import utc_now

logger = logging.getLogger(__name__)


def collect_raw_filenames(resources: list[dict[str, Any]]) -> list[str]:
    return [
        name
        for row in resources
        if row["type"] == "raw" and (name := filename_from_raw_location(row["location"]))
    ]


def validate_completion_input(content: str, run_options: dict[str, Any] | None) -> tuple[str, dict[str, Any]]:
    """校验单轮提问正文与 run_options 边界参数。"""
    cleaned = content.strip()
    if not cleaned:
        raise ValidationError("content 不能为空")
    options = run_options or {}
    if set(options) - {"tool_execution_timeout"}:
        raise ValidationError("未知的 run_options 字段")
    timeout = options.get("tool_execution_timeout")
    if timeout is not None and (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not math.isfinite(timeout)
        or timeout <= 0
    ):
        raise ValidationError("工具超时必须为有限正数")
    return cleaned, options


async def recover_active_turn(database: DatabaseProtocol, session_id: str, turn_id: str | None) -> None:
    """事务写失败后的尽力收口：活跃轮标 failed、清空 session.active_turn_id。"""

    def recover() -> None:
        db = database.connect()
        with crud.transaction(db):
            if turn_id is not None:
                crud.update_turn_status_if_current(
                    db,
                    turn_id=turn_id,
                    current_statuses={"queued", "in_progress", "cancelling"},
                    status="failed",
                    now=utc_now(),
                    error="storage_failure",
                )
            crud.update_session(
                db,
                session_id=session_id,
                now=utc_now(),
                clear_active_turn=True,
                status="ready",
            )

    try:
        await asyncio.to_thread(recover)
    except Exception:
        pass


async def generate_and_persist_title(
    *,
    session_id: str,
    question: str,
    filenames: list[str],
    agent_client: AgentGateway,
    database: DatabaseProtocol,
    timeout_seconds: float,
    is_inactive: Callable[[], bool],
    on_persisted: Callable[[str], Awaitable[None]],
) -> None:
    """后台总结可读标题并条件写入空标题会话，不阻塞主问答 SSE 流。"""
    title = ""
    generator = getattr(agent_client, "generate_title", None)
    if callable(generator):
        try:
            raw_title = await asyncio.wait_for(
                generator(
                    question=question,
                    filenames=filenames,
                    timeout_seconds=timeout_seconds,
                ),
                timeout=timeout_seconds,
            )
            title = clean_session_title(raw_title)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.debug("Session title generation fell back for %s: %s", session_id, exc)
    if not title:
        title = fallback_session_title(
            first_user_message=question,
            first_filename=filenames[0] if filenames else None,
        )
    if is_inactive():
        return

    def persist() -> dict[str, Any] | None:
        db = database.connect()
        with crud.transaction(db):
            return crud.set_session_title_if_empty(db, session_id=session_id, title=title)

    loop = asyncio.get_running_loop()
    db_future = loop.run_in_executor(None, persist)
    try:
        updated = await asyncio.shield(db_future)
    except asyncio.CancelledError:
        # 线程中的 SQLite 事务无法中途强杀，二次取消仍须等到线程退出后才允许关闭数据库连接。
        while not db_future.done():
            try:
                await asyncio.shield(db_future)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        return
    except Exception as exc:
        logger.debug("Session title persistence skipped for %s: %s", session_id, exc)
        return

    if updated is None or is_inactive():
        return
    await on_persisted(updated["title"])
