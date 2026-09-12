"""捕获边界后按需读数据库历史，合并当前轮副本，不缓存到 manager。"""

import asyncio
import copy
import json
from dataclasses import dataclass

from backend.services.subscription import Subscription
from backend.services.turn_view import TurnView
from backend.services.errors import BackendServiceError


@dataclass
class ResumeContext:
    session_id: str
    turn_id: str | None
    boundary: int
    session: dict
    resources: list
    current_turn: dict | None
    subscription: Subscription
    max_bytes: int


async def build_snapshot(database, context):
    def read():
        views = {}
        total = 0
        rows = database.connect().execute(
            "SELECT turn_id, event_type, payload_json FROM chat_events "
            "WHERE session_id=? AND sequence<=? ORDER BY sequence",
            (context.session_id, context.boundary),
        )
        active_id = context.current_turn["id"] if context.current_turn else None
        for row in rows:
            if row["turn_id"] is None or row["turn_id"] == active_id:
                continue
            total += len(row["payload_json"].encode("utf-8"))
            if total > context.max_bytes:
                raise BackendServiceError("会话历史超过恢复预算")
            view = views.setdefault(row["turn_id"], TurnView(row["turn_id"]))
            view.apply({"type": row["event_type"], "payload": json.loads(row["payload_json"])})
        turns = [view.snapshot() for view in views.values()]
        if context.current_turn:
            turns.append(copy.deepcopy(context.current_turn))
        result = {"session_id": context.session_id, "state": {
            "status": context.session["status"], "active_turn_id": context.session["active_turn_id"],
            "resources": context.resources, "turns": turns,
        }}
        if len(json.dumps(result, ensure_ascii=False).encode("utf-8")) > context.max_bytes:
            raise BackendServiceError("会话快照超过恢复预算")
        return result
    return await asyncio.to_thread(read)
