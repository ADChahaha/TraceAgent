"""读取 chat_messages 与 chat_turns 渲染历史轮，合并当前轮内存副本，不重放事件。"""

import asyncio
import copy
import json
from dataclasses import dataclass

from backend.crud import crud
from backend.services.subscription import Subscription
from backend.services.errors import BackendServiceError


@dataclass
class ResumeContext:
    session_id: str
    turn_id: str | None
    turn_ids: list
    session: dict
    resources: list
    current_turn: dict | None
    subscription: Subscription
    max_bytes: int


def _tool_detail(row):
    detail = {"tool_call_id": row["tool_call_id"], "tool": row["name"]}
    try:
        parsed = json.loads(row["content"])
    except ValueError:
        parsed = None
    if isinstance(parsed, dict) and "error" in parsed:
        detail["error"] = parsed["error"]
        status = "failed"
    else:
        detail["result_json"] = row["content"]
        status = "completed"
    return status, detail


def _render_items(messages):
    items = []
    for row in messages:
        role = row["role"]
        if role == "user":
            items.append({"id": row["id"], "kind": "user", "text": row["content"], "status": "completed"})
        elif role == "assistant":
            item = {"id": "message:" + row["id"], "kind": "assistant", "text": row["content"], "status": "completed"}
            calls = json.loads(row["tool_calls_json"] or "[]")
            if calls:
                item["tool_calls"] = [{"id": call["id"], "name": call["function"]["name"],
                                       "args_json": call["function"].get("arguments", "{}")} for call in calls]
            items.append(item)
        elif role == "tool":
            status, detail = _tool_detail(row)
            items.append({"id": "tool:" + row["tool_call_id"], "kind": "tool",
                          "name": row["name"], "status": status, "detail": detail})
    return items


async def build_snapshot(database, context):
    def read():
        db = database.connect()
        active_id = context.current_turn["id"] if context.current_turn else None
        messages_by_turn = {}
        for row in crud.list_messages(db, context.session_id):
            if row["turn_id"] is not None:
                messages_by_turn.setdefault(row["turn_id"], []).append(row)
        turn_rows = {turn["id"]: turn for turn in crud.list_turns(db, context.session_id)}
        turns = []
        # 只渲染 attach 时已存在的轮次；之后新建的轮由订阅增量送达，避免重复。
        for turn_id in context.turn_ids:
            if turn_id == active_id:
                continue
            turn = turn_rows.get(turn_id)
            if turn is None:
                continue
            turns.append({"id": turn["id"], "status": turn["status"], "error": turn["error"],
                          "items": _render_items(messages_by_turn.get(turn["id"], []))})
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
