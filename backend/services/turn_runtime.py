"""单轮自治执行体：建轮、gRPC 消费、工具组配对、消息落库、终态收口。

对应 codex-core 的 Session+turn 循环：轮内全部状态（配对组、展示视图、序号）
和写事务壳（连接、BEGIN、提交、线程调度）归本任务私有；对 manager 没有任何
直接引用，依赖以启动参数注入：session_id、agent_client、database 是数据依赖，
refresh/publish/fail 是 manager 提供的回调通道（缓存同步、事件广播、损坏标记）。
"""

import asyncio
import copy
import json
import uuid

from backend.crud import crud
from backend.services.time_utils import utc_now
from backend.services.turn_view import TurnView


class TurnRuntime:
    def __init__(self, *, session_id, agent_client, database, refresh, publish, fail, turn_id, content, run_options):
        self.session_id = session_id
        self.agent_client = agent_client
        self.database = database
        self.refresh = refresh
        self.publish = publish
        self.fail = fail
        self.turn_id = turn_id
        self.content = content
        self.run_options = run_options
        self.call = None
        self.cancel_requested = False
        self.task = None
        self.done = asyncio.Event()
        self.begun = asyncio.Event()
        self.begin_error = None
        self.error = None
        self.status = "queued"
        self.view = TurnView(turn_id)
        self.pending_groups, self.completed_groups, self.last_seq = {}, {}, 0
        self.broadcast_count = 0

    def start(self):
        self.task = asyncio.create_task(self.run(), name=f"turn:{self.turn_id}")

    async def wait_closed(self):
        if self.task:
            await asyncio.gather(self.task, return_exceptions=True)

    def cancel(self):
        """manager 的唯一反向通道：只设标志，不进队列、不打断写事务。
        run() 在各检查点观察标志退出；gRPC 流由 call.cancel() 断开。"""
        self.cancel_requested = True
        if self.call is not None:
            self.call.cancel()

    async def run(self):
        try:
            request = await self._begin()
            if request is not None and not self.cancel_requested:
                self.call = self.agent_client.chat_completion(**request, run_options=self.run_options)
                if not self.cancel_requested:
                    async for event in self.call:
                        if not await self._on_event(event):
                            break
            if self.status == "queued":
                if self.cancel_requested:
                    await self._finish("cancelled", "执行已取消")
                else:
                    await self._finish("failed", "agent 未返回终态便结束流")
        except asyncio.CancelledError:
            await self._finish("cancelled", "执行已取消")
        except Exception as exc:
            await self._finish("failed", str(exc))
        finally:
            if self.call is not None:
                self.call.cancel()
            self.done.set()

    async def _begin(self):
        """建轮事务：创建 turn、用户消息、认领 active_turn_id，并返回模型请求输入。
        结果经 begun 信号告知创建方；失败时 begin_error 携带异常。"""
        try:
            request = await self._write(self._begin_operation())
        except BaseException as exc:
            self.begin_error = exc
            raise
        finally:
            self.begun.set()
        return request

    def _begin_operation(self):
        def begin(db, events):
            now = utc_now()
            crud.create_turn(db, turn_id=self.turn_id, session_id=self.session_id, status="queued", now=now, commit=False)
            message_id = uuid.uuid4().hex
            crud.create_message(db, message_id=message_id, session_id=self.session_id, turn_id=self.turn_id, role="user",
                                content=self.content, now=now, sequence=crud.get_next_message_sequence(db, self.turn_id),
                                group_id=message_id, group_index=0, commit=False)
            crud.update_turn(db, turn_id=self.turn_id, now=now, status="in_progress", agent_completion_id=self.turn_id, commit=False)
            crud.update_session(db, session_id=self.session_id, now=now, status="running", active_turn_id=self.turn_id, commit=False)
            self._emit(events, "turn.created")
            self._emit(events, "message.created", {"message_id": message_id, "role": "user", "content": self.content})
            self._emit(events, "turn.started")
            messages = [{"role": row["role"], "content": row["content"], "tool_calls_json": row["tool_calls_json"],
                         **{key: row[key] for key in ("tool_call_id", "name") if row[key] is not None}}
                        for row in crud.list_messages(db, self.session_id)]
            return {"completion_id": self.turn_id,
                    "resource_path": [{"type": row["type"], "location": row["location"]} for row in crud.list_resources(db, self.session_id)],
                    "messages": messages}

        return begin

    async def _on_event(self, event):
        """处理一条 agent 事件：校验、配组、落库、广播。返回 False 停止读取。"""
        if self.cancel_requested:
            return False
        kind, seq = event["type"], event.get("seq")
        if seq and seq <= self.last_seq:
            raise ValueError("agent 事件序号重复或倒退")
        if kind.startswith("model_message.") and not event.get("message_id"):
            raise ValueError("模型事件缺少 message_id")
        if kind in {"tool_started", "tool_completed", "tool_failed"} and not event.get("tool_call_id"):
            raise ValueError("工具事件缺少 tool_call_id")
        if kind == "completion.completed":
            if self.pending_groups:
                raise ValueError("agent 完成时仍有未配齐的工具消息组")
            await self._finish("completed")
            return False
        if kind in {"completion.failed", "completion.cancelled"}:
            await self._finish("failed" if kind.endswith("failed") else "cancelled",
                               event.get("error_message") or event.get("error"))
            return False
        ready = None
        if kind == "model_message.done":
            ready = self._accept_model_message(event)
        elif kind in {"tool_completed", "tool_failed"}:
            ready = self._accept_tool_result(kind, event)

        await self._write(self._event_operation(kind, event, ready))
        if ready:
            self.completed_groups[ready[0]] = True
        if seq:
            self.last_seq = seq
        return True

    def _accept_model_message(self, event):
        mid, calls = event["message_id"], event.get("tool_calls", [])
        if mid in self.completed_groups or mid in self.pending_groups:
            raise ValueError("重复的模型完整消息")
        ids = [call["id"] for call in calls]
        if any(not item for item in ids) or len(set(ids)) != len(ids):
            raise ValueError("工具调用 ID 必须非空且唯一")
        if any(not call.get("name") for call in calls):
            raise ValueError("工具调用缺少名称")
        for call in calls:
            json.loads(call.get("args_json", "{}"))
        group = {"assistant": event, "results": {}}
        if calls:
            self.pending_groups[mid] = group
            return None
        return (mid, group)

    def _accept_tool_result(self, kind, event):
        if "result_json" not in event and not (kind == "tool_failed" and (event.get("error") or event.get("error_message"))):
            raise ValueError("工具结果缺少实际返回内容")
        call_id = event["tool_call_id"]
        matches = [(mid, group) for mid, group in self.pending_groups.items()
                   if any(call["id"] == call_id for call in group["assistant"]["tool_calls"])]
        if len(matches) != 1:
            raise ValueError("工具结果无法唯一匹配待提交组")
        mid, group = matches[0]
        if call_id in group["results"]:
            raise ValueError("重复的工具结果")
        group["results"][call_id] = event
        if len(group["results"]) == len(group["assistant"]["tool_calls"]):
            self.pending_groups.pop(mid)
            return (mid, group)
        return None

    def _event_operation(self, kind, event, ready):
        def save(db, events):
            self._emit(events, kind, event)
            if ready:
                self._save_group(db, *ready)

        return save

    def _save_group(self, db, mid, group):
        assistant = group["assistant"]
        calls = assistant.get("tool_calls", [])
        tool_calls = [{"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": c.get("args_json", "{}")}} for c in calls]
        messages = [{"role": "assistant", "content": assistant.get("content", ""), "tool_calls_json": json.dumps(tool_calls, ensure_ascii=False)}]
        for call in calls:
            result = group["results"][call["id"]]
            content = result.get("result_json")
            if content is None:
                content = json.dumps({"error": result.get("error_message") or result["error"]}, ensure_ascii=False)
            json.loads(content)
            messages.append({"role": "tool", "content": content, "tool_call_id": call["id"], "name": call["name"]})
        sequence = crud.get_next_message_sequence(db, self.turn_id)
        for index, message in enumerate(messages):
            crud.create_message(db, message_id=uuid.uuid4().hex, session_id=self.session_id, turn_id=self.turn_id,
                                now=utc_now(), sequence=sequence + index, group_id=mid, group_index=index, commit=False, **message)

    async def _finish(self, status, error=None):
        """写轮终态并清空 session 活跃标记；写失败时不无限重试。"""
        if self.status != "queued":
            return
        self.status = status
        self.error = error
        try:
            await self._write(self._finish_operation(status, error))
        except Exception:
            return
        self.pending_groups.clear()
        self.completed_groups.clear()

    def _finish_operation(self, status, error):
        def finish(db, events):
            now = utc_now()
            row = crud.update_turn_status_if_current(db, turn_id=self.turn_id,
                                                     current_statuses={"queued", "in_progress", "cancelling"},
                                                     status=status, now=now, error=error, completed_at=now, commit=False)
            if row is None:
                return
            if status == "cancelled":
                self._emit(events, "turn.cancel_requested")
            crud.update_session(db, session_id=self.session_id, now=now, clear_active_turn=True,
                                status="ready", commit=False)
            self._emit(events, "turn." + status, {"error": error})

        return finish

    async def _write(self, operation):
        """开事务执行并提交；事务内的会话与资源快照经 refresh 回调同步到 manager
        缓存，事件先入展示视图再经 publish 回调逐条转发；事务或广播失败经 fail
        回调标记 manager 损坏。"""
        events = []

        def execute():
            db = self.database.connect()
            with crud.transaction(db):
                result = operation(db, events)
                return result, crud.get_session(db, self.session_id), crud.list_resources(db, self.session_id)

        try:
            result, session, resources = await asyncio.to_thread(execute)
        except Exception:
            self.fail()
            raise
        self.refresh(session, resources)
        try:
            for event in events:
                self.view.apply(event)
                self.broadcast_count += 1
                await self.publish(event)
        except Exception:
            self.fail()
            raise
        return result

    def _emit(self, events, kind, payload=None):
        events.append({"type": kind, "turn_id": self.turn_id, "payload": payload or {}})

    def snapshot(self):
        return self.view.snapshot()
