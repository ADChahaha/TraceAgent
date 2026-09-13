"""会话命令串行化：事务提交 → 当前轮快照 → 每连接广播。网络由 TurnRuntime 执行。"""

import asyncio
import copy
import json
import sqlite3
import uuid
from dataclasses import dataclass

from backend.crud import crud
from backend.services.errors import BackendServiceError, ConflictError, NotFoundError
from backend.services.session_history import ResumeContext
from backend.services.subscription import Subscription
from backend.services.time_utils import utc_now
from backend.services.turn_runtime import TurnRuntime
from backend.services.turn_view import TurnView

TERMINAL = {"completed", "cancelled", "failed"}
INTERNAL = {"start", "event", "stop"}
CLOSING_ALLOWED = {"cancel", "detach", "ended", "stop"}
BROKEN_ALLOWED = {"detach", "ended", "stop"}


@dataclass
class Command:
    name: str
    args: tuple
    reply: asyncio.Future | None = None


class SessionManager:
    def __init__(self, *, session, resources, database, agent_client, settings):
        self.session_id = session["id"]
        self.session = session
        self.resources = resources
        self.database = database
        self.agent_client = agent_client
        self.settings = settings
        self.current_turn_state = None
        self.runtimes, self.subscribers = {}, {}
        self.pending_groups, self.completed_groups, self.last_agent_seq = {}, {}, {}
        self.commands = asyncio.Queue(maxsize=settings.session_command_limit)
        self.closed = self.closing = self.broken = False
        self.last_activity = asyncio.get_running_loop().time()
        self.task = asyncio.create_task(self._run(), name=f"session:{self.session_id}")

    @property
    def active_turn_id(self):
        return self.session["active_turn_id"]

    def _fail(self):
        self.broken = True
        for runtime in self.runtimes.values():
            runtime.cancel()
        for subscription in self.subscribers.values():
            subscription.close()

    def _recycle_subscription(self, result):
        if isinstance(result, ResumeContext):
            result.subscription.close()
            self.subscribers.pop(result.subscription.id, None)

    async def _ask(self, name, *args):
        if self.closed or (self.closing and name not in CLOSING_ALLOWED):
            raise BackendServiceError("会话管理器已关闭")
        reply = asyncio.get_running_loop().create_future()
        command = Command(name, args, reply)
        if name in INTERNAL:
            await self.commands.put(command)
        else:
            try:
                self.commands.put_nowait(command)
            except asyncio.QueueFull:
                raise BackendServiceError("会话命令队列繁忙") from None
        try:
            return await reply
        except asyncio.CancelledError:
            # 命令已入队仍会执行；同步守卫覆盖 handler 已 set_result 但调用方不再接收的窗口。
            if reply.done() and not reply.cancelled() and reply.exception() is None:
                self._recycle_subscription(reply.result())
            raise

    async def _tell(self, name, *args):
        if not self.closed:
            await self.commands.put(Command(name, args))

    async def _run(self):
        while True:
            command = await self.commands.get()
            self.last_activity = asyncio.get_running_loop().time()
            try:
                if self.broken and command.name not in BROKEN_ALLOWED:
                    raise BackendServiceError("会话存储异常，请恢复服务后重试")
                result = await getattr(self, "_handle_" + command.name)(*command.args)
            except Exception as exc:
                if isinstance(exc, sqlite3.Error):
                    self._fail()
                if command.reply is not None and not command.reply.done():
                    command.reply.set_exception(exc)
            else:
                if command.reply is not None:
                    if command.reply.cancelled():
                        self._recycle_subscription(result)  # 调用方已取消，回收 handler 产生的订阅
                    elif not command.reply.done():
                        command.reply.set_result(result)
            finally:
                self.commands.task_done()
            if command.name == "stop":
                return

    async def _write(self, operation):
        events = []

        def execute():
            db = self.database.connect()
            with crud.transaction(db):
                result = operation(db, events)
                return result, crud.get_session(db, self.session_id), crud.list_resources(db, self.session_id)

        result, self.session, self.resources = await asyncio.to_thread(execute)
        try:
            for event in events:
                if event["type"] == "turn.created":
                    self.current_turn_state = TurnView(event["turn_id"])
                if self.current_turn_state and event["turn_id"] == self.current_turn_state.id:
                    self.current_turn_state.apply(event)
                for key, subscription in list(self.subscribers.items()):
                    if not subscription.publish(event):
                        self.subscribers.pop(key, None)
                if event["type"] in {"turn.completed", "turn.failed", "turn.cancelled"}:
                    self.current_turn_state = None
        except Exception:
            self._fail()
            raise
        return result

    def _emit(self, events, kind, turn_id=None, payload=None):
        events.append({"type": kind, "turn_id": turn_id, "payload": payload or {}})

    async def create_completion(self, *, content, files, run_options):
        return await self._ask("create", content, files, run_options)

    async def _handle_create(self, content, files, run_options):
        if self.active_turn_id:
            raise ConflictError("会话已有活跃轮次")
        if self.session["status"] == "failed" and not files:
            raise ConflictError("资源准备失败，需要重新上传文件")
        turn_id = uuid.uuid4().hex

        def create(db, events):
            now = utc_now()
            crud.create_turn(db, turn_id=turn_id, session_id=self.session_id, status="queued", now=now, commit=False)
            message_id = uuid.uuid4().hex
            crud.create_message(db, message_id=message_id, session_id=self.session_id, turn_id=turn_id, role="user", content=content,
                                now=now, sequence=crud.get_next_message_sequence(db, self.session_id), group_id=message_id, group_index=0, commit=False)
            crud.update_session(db, session_id=self.session_id, now=now, status="processing" if files else "running", active_turn_id=turn_id, commit=False)
            self._emit(events, "turn.created", turn_id)
            self._emit(events, "message.created", turn_id, {"message_id": message_id, "role": "user", "content": content})

        await self._write(create)
        runtime = TurnRuntime(self, turn_id, files, run_options)
        self.runtimes[turn_id] = runtime
        context = await self._handle_attach()
        try:
            runtime.start()
        except Exception as exc:
            self.runtimes.pop(turn_id, None)
            await self._finish(turn_id, "failed", str(exc))
            self._recycle_subscription(context)
            raise
        return context

    def _valid(self, turn_id, generation):
        runtime = self.runtimes.get(turn_id)
        return runtime is not None and runtime.generation == generation and self.active_turn_id == turn_id and not runtime.cancel_requested

    async def start_turn(self, turn_id, generation):
        return await self._ask("start", turn_id, generation)

    async def _handle_start(self, turn_id, generation):
        if not self._valid(turn_id, generation):
            return None

        def start(db, events):
            now = utc_now()
            crud.update_turn(db, turn_id=turn_id, now=now, status="in_progress", agent_completion_id=turn_id, commit=False)
            crud.update_session(db, session_id=self.session_id, now=now, status="running", commit=False)
            self._emit(events, "turn.started", turn_id)
            messages = [{"role": row["role"], "content": row["content"], "tool_calls_json": row["tool_calls_json"],
                         **{key: row[key] for key in ("tool_call_id", "name") if row[key] is not None}}
                        for row in crud.list_messages(db, self.session_id)]
            refs = [{"type": row["type"], "location": row["location"]} for row in crud.list_resources(db, self.session_id)]
            return {"completion_id": turn_id, "resource_path": refs, "messages": messages}

        return await self._write(start)

    async def resources_prepared(self, turn_id, generation, refs):
        await self._tell("resources", turn_id, generation, refs)

    async def _handle_resources(self, turn_id, generation, refs):
        if not self._valid(turn_id, generation):
            return

        def save(db, events):
            crud.delete_resources(db, self.session_id, commit=False)
            for ref in refs:
                crud.create_resource(db, resource_id=uuid.uuid4().hex, session_id=self.session_id, resource_type=ref["type"],
                                     location=ref["location"], now=utc_now(), commit=False)
            self._emit(events, "resources.prepared", turn_id, {"resources": refs})

        await self._write(save)

    async def agent_event(self, turn_id, generation, event):
        return await self._ask("event", turn_id, generation, event)

    async def _handle_event(self, turn_id, generation, event):
        if not self._valid(turn_id, generation) or self.current_turn_state.status != "in_progress":
            return False
        kind, seq = event["type"], event.get("seq")
        if seq and seq <= self.last_agent_seq.get(turn_id, 0):
            raise ValueError("agent 事件序号重复或倒退")
        if kind.startswith("model_message.") and not event.get("message_id"):
            raise ValueError("模型事件缺少 message_id")
        if kind in {"tool_started", "tool_completed", "tool_failed"} and not event.get("tool_call_id"):
            raise ValueError("工具事件缺少 tool_call_id")
        if kind == "completion.completed":
            if self.pending_groups:
                raise ValueError("agent 完成时仍有未配齐的工具消息组")
            await self._finish(turn_id, "completed")
            return False
        if kind in {"completion.failed", "completion.cancelled"}:
            await self._finish(turn_id, "failed" if kind.endswith("failed") else "cancelled", event.get("error_message") or event.get("error"))
            return False
        pending, completed = copy.deepcopy(self.pending_groups), copy.deepcopy(self.completed_groups)
        ready = None
        if kind == "model_message.done":
            mid, calls = event["message_id"], event.get("tool_calls", [])
            if mid in completed or mid in pending:
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
                pending[mid] = group
            else:
                ready = (mid, group)
        elif kind in {"tool_completed", "tool_failed"}:
            if "result_json" not in event and not (kind == "tool_failed" and (event.get("error") or event.get("error_message"))):
                raise ValueError("工具结果缺少实际返回内容")
            call_id = event["tool_call_id"]
            matches = [(mid, group) for mid, group in pending.items() if any(call["id"] == call_id for call in group["assistant"]["tool_calls"])]
            if len(matches) != 1:
                raise ValueError("工具结果无法唯一匹配待提交组")
            mid, group = matches[0]
            if call_id in group["results"]:
                raise ValueError("重复的工具结果")
            group["results"][call_id] = event
            if len(group["results"]) == len(group["assistant"]["tool_calls"]):
                ready = (mid, group)
                pending.pop(mid)

        def save(db, events):
            self._emit(events, kind, turn_id, event)
            if ready:
                self._save_group(db, turn_id, *ready)

        await self._write(save)
        if ready:
            completed[ready[0]] = True
        self.pending_groups, self.completed_groups = pending, completed
        if seq:
            self.last_agent_seq[turn_id] = seq
        return True

    def _save_group(self, db, turn_id, mid, group):
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
        sequence = crud.get_next_message_sequence(db, self.session_id)
        for index, message in enumerate(messages):
            crud.create_message(db, message_id=uuid.uuid4().hex, session_id=self.session_id, turn_id=turn_id, now=utc_now(),
                                sequence=sequence + index, group_id=f"{turn_id}:{mid}", group_index=index, commit=False, **message)

    async def _finish(self, turn_id, status, error=None):
        def finish(db, events):
            now = utc_now()
            row = crud.update_turn_status_if_current(db, turn_id=turn_id, current_statuses={"queued", "in_progress", "cancelling"},
                                                     status=status, now=now, error=error, completed_at=now, commit=False)
            if row is None:
                return crud.get_turn(db, turn_id)
            if status == "cancelled":
                self._emit(events, "turn.cancel_requested", turn_id)
            crud.update_session(db, session_id=self.session_id, now=now, clear_active_turn=True,
                                status="failed" if self.session["status"] == "processing" else "ready", commit=False)
            self._emit(events, "turn." + status, turn_id, {"error": error})
            return row

        result = await self._write(finish)
        self.pending_groups.clear()
        self.completed_groups.clear()
        self.last_agent_seq.pop(turn_id, None)
        return result

    async def cancel(self, turn_id):
        return await self._ask("cancel", turn_id)

    async def _handle_cancel(self, turn_id):
        row = await asyncio.to_thread(lambda: crud.get_turn(self.database.connect(), turn_id))
        if row is None or row["session_id"] != self.session_id:
            raise NotFoundError("轮次不存在")
        if row["status"] in TERMINAL:
            return row
        if self.active_turn_id != turn_id:
            raise ConflictError("该轮次不是当前活跃轮次")
        result = await self._finish(turn_id, "cancelled")
        if turn_id in self.runtimes:
            self.runtimes[turn_id].cancel()
        return result

    async def worker_ended(self, turn_id, generation, error):
        await self._tell("ended", turn_id, generation, error)

    async def _handle_ended(self, turn_id, generation, error):
        runtime = self.runtimes.get(turn_id)
        if runtime is None or runtime.generation != generation:
            return
        if self.active_turn_id == turn_id and not self.broken:
            await self._finish(turn_id, "failed", error)
        self.runtimes.pop(turn_id, None)

    async def attach(self):
        return await self._ask("attach")

    async def _handle_attach(self):
        turn_ids = await asyncio.to_thread(
            lambda: [turn["id"] for turn in crud.list_turns(self.database.connect(), self.session_id)])
        subscription = Subscription(max_events=self.settings.subscription_max_events, max_bytes=self.settings.subscription_max_bytes)
        self.subscribers[subscription.id] = subscription
        return ResumeContext(self.session_id, self.active_turn_id, turn_ids, copy.deepcopy(self.session),
                             copy.deepcopy(self.resources), self.current_turn_state.snapshot() if self.current_turn_state else None,
                             subscription, self.settings.snapshot_max_bytes)

    async def detach(self, subscription_id):
        if not self.closed:
            await self._ask("detach", subscription_id)

    async def _handle_detach(self, subscription_id):
        subscription = self.subscribers.pop(subscription_id, None)
        if subscription:
            subscription.close()

    def idle(self):
        return not self.active_turn_id and not self.runtimes and not self.subscribers and self.commands.empty()

    async def close(self):
        if self.closed:
            return
        self.closing = True
        if self.active_turn_id and not self.broken:
            await self.cancel(self.active_turn_id)
        runtimes = list(self.runtimes.values())
        for runtime in runtimes:
            runtime.cancel()
        await asyncio.gather(*(runtime.wait_closed() for runtime in runtimes), return_exceptions=True)
        await self._ask("stop")
        await self.task

    async def _handle_stop(self):
        self.closed = True
        for subscription in self.subscribers.values():
            subscription.close()
        self.subscribers.clear()
