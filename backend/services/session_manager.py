"""会话命令串行化：事务提交 → 当前轮快照 → 每连接广播。网络由 TurnRuntime 执行。"""

import asyncio
import copy
import json
import sqlite3
import uuid

from backend.core.db import transaction
from backend.crud import crud
from backend.services.errors import BackendServiceError, ConflictError, NotFoundError
from backend.services.session_history import ResumeContext
from backend.services.subscription import Subscription
from backend.services.time_utils import utc_now
from backend.services.turn_runtime import TurnRuntime
from backend.services.turn_view import TurnView


TERMINAL = {"completed", "cancelled", "failed"}


class SessionManager:
    def __init__(self, *, session, resources, last_event_seq, database, agent_client, settings):
        self.session_id = session["id"]
        self.session = session
        self.resources = resources
        self.last_event_seq = last_event_seq
        self.database = database
        self.agent_client = agent_client
        self.settings = settings
        self.current_turn_state = None
        self.runtimes = {}
        self.subscribers = {}
        self.pending_groups = {}
        self.completed_groups = {}
        self.last_agent_seq = {}
        self.commands = asyncio.Queue(maxsize=settings.session_command_limit)
        self.closed = False
        self.closing = False
        self.broken = False
        self.last_activity = asyncio.get_running_loop().time()
        self.task = asyncio.create_task(self._run(), name=f"session:{self.session_id}")

    @property
    def active_turn_id(self):
        return self.session["active_turn_id"]

    async def _ask(self, name, *args):
        if self.closed or (self.closing and name not in {"cancel", "detach", "ended", "stop"}):
            raise BackendServiceError("会话管理器已关闭")
        internal = name in {"start", "event", "resources", "ended", "stop"}
        if self.commands.full() and not internal:
            raise BackendServiceError("会话命令队列繁忙")
        future = asyncio.get_running_loop().create_future()
        if internal:
            await self.commands.put((name, args, future))
        else:
            self.commands.put_nowait((name, args, future))
        try:
            return await asyncio.shield(future)
        except asyncio.CancelledError:
            # 请求退出不撤销已经接管的业务；如果稍后产生订阅，则回收它。
            def discard(done):
                if done.cancelled():
                    return
                exc = done.exception()
                if exc is None and isinstance(done.result(), ResumeContext):
                    context = done.result()
                    context.subscription.close()
                    self.subscribers.pop(context.subscription.id, None)
            future.add_done_callback(discard)
            raise

    async def _run(self):
        while True:
            name, args, future = await self.commands.get()
            self.last_activity = asyncio.get_running_loop().time()
            try:
                if self.broken and name not in {"detach", "ended", "stop"}:
                    raise BackendServiceError("会话存储异常，请恢复服务后重试")
                result = await getattr(self, "_handle_" + name)(*args)
            except Exception as exc:
                if isinstance(exc, sqlite3.Error):
                    self.broken = True
                    for runtime in self.runtimes.values():
                        runtime.cancel()
                    for subscription in self.subscribers.values():
                        subscription.close()
                if not future.done():
                    future.set_exception(exc)
            else:
                if not future.done():
                    future.set_result(result)
            finally:
                self.commands.task_done()
            if name == "stop":
                return

    async def _write(self, operation):
        events = []
        def execute():
            db = self.database.connect()
            with transaction(db):
                result = operation(db, events)
                session = crud.get_session(db, self.session_id)
                resources = crud.list_resources(db, self.session_id)
            return result, session, resources
        result, self.session, self.resources = await asyncio.to_thread(execute)
        try:
            for event in events:
                self.last_event_seq = event["seq"]
                if event["type"] == "turn.created":
                    self.current_turn_state = TurnView(event["turn_id"])
                if self.current_turn_state and event["turn_id"] == self.current_turn_state.id:
                    self.current_turn_state.apply(event)
                self._broadcast(event)
                if event["type"] in {"turn.completed", "turn.failed", "turn.cancelled"}:
                    self.current_turn_state = None
        except Exception:
            self.broken = True
            for runtime in self.runtimes.values():
                runtime.cancel()
            for subscription in self.subscribers.values():
                subscription.close()
            raise
        return result

    def _emit(self, db, events, kind, turn_id=None, payload=None):
        row = crud.create_event(db, event_id=uuid.uuid4().hex, session_id=self.session_id,
                                turn_id=turn_id, event_type=kind, payload=payload or {}, now=utc_now(), commit=False)
        events.append({"session_id": self.session_id, "turn_id": turn_id,
                       "seq": row["sequence"], "type": kind, "payload": payload or {}})

    def _broadcast(self, event):
        for key, subscription in list(self.subscribers.items()):
            if not subscription.publish(event):
                self.subscribers.pop(key, None)

    async def create_completion(self, *, content, files, run_options, request_id, fingerprint):
        return await self._ask("create", content, files, run_options, request_id, fingerprint)

    async def _handle_create(self, content, files, run_options, request_id, fingerprint):
        if self.active_turn_id:
            raise ConflictError("会话已有活跃轮次")
        if self.session["status"] == "failed" and not files:
            raise ConflictError("资源准备失败，需要重新上传文件")
        turn_id = uuid.uuid4().hex
        def create(db, events):
            now = utc_now()
            crud.create_turn(db, turn_id=turn_id, session_id=self.session_id, status="queued", now=now, commit=False)
            sequence = db.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM chat_messages WHERE session_id=?", (self.session_id,)).fetchone()[0]
            message_id = uuid.uuid4().hex
            crud.create_message(db, message_id=message_id, session_id=self.session_id,
                                turn_id=turn_id, role="user", content=content, now=now,
                                sequence=sequence, group_id=message_id, group_index=0, commit=False)
            crud.update_session(db, session_id=self.session_id, now=now, status="processing" if files else "running", active_turn_id=turn_id, commit=False)
            self._emit(db, events, "turn.created", turn_id, {"request_id": request_id, "fingerprint": fingerprint})
            self._emit(db, events, "message.created", turn_id, {"message_id": message_id, "role": "user", "content": content})
        await self._write(create)
        runtime = TurnRuntime(self, turn_id, files, run_options)
        self.runtimes[turn_id] = runtime
        context = await self._handle_attach()
        try:
            runtime.start()
        except Exception as exc:
            self.runtimes.pop(turn_id, None)
            await self._finish(turn_id, "failed", str(exc))
            context.subscription.close()
            self.subscribers.pop(context.subscription.id, None)
            raise
        return context

    def _valid(self, turn_id, generation):
        runtime = self.runtimes.get(turn_id)
        return (runtime is not None and runtime.generation == generation
                and self.active_turn_id == turn_id and not runtime.cancel_requested)

    async def start_turn(self, turn_id, generation):
        return await self._ask("start", turn_id, generation)

    async def _handle_start(self, turn_id, generation):
        if not self._valid(turn_id, generation):
            return None
        def start(db, events):
            crud.update_turn(db, turn_id=turn_id, now=utc_now(), status="in_progress", agent_completion_id=turn_id, commit=False)
            crud.update_session(db, session_id=self.session_id, now=utc_now(), status="running", commit=False)
            self._emit(db, events, "turn.started", turn_id)
            messages = []
            for row in crud.list_messages(db, self.session_id):
                item = {"role": row["role"], "content": row["content"], "tool_calls_json": row["tool_calls_json"]}
                for key in ("tool_call_id", "name"):
                    if row[key] is not None:
                        item[key] = row[key]
                messages.append(item)
            refs = [{"type": row["type"], "location": row["location"]} for row in crud.list_resources(db, self.session_id)]
            return {"completion_id": turn_id, "resource_path": refs, "messages": messages}
        return await self._write(start)

    async def resources_prepared(self, turn_id, generation, refs):
        return await self._ask("resources", turn_id, generation, refs)

    async def _handle_resources(self, turn_id, generation, refs):
        if not self._valid(turn_id, generation):
            return
        def save(db, events):
            db.execute("DELETE FROM chat_resources WHERE session_id=?", (self.session_id,))
            for ref in refs:
                crud.create_resource(db, resource_id=uuid.uuid4().hex, session_id=self.session_id,
                                     resource_type=ref["type"], location=ref["location"], now=utc_now(), commit=False)
            self._emit(db, events, "resources.prepared", turn_id, {"resources": refs})
        await self._write(save)

    async def agent_event(self, turn_id, generation, event):
        return await self._ask("event", turn_id, generation, event)

    async def _handle_event(self, turn_id, generation, event):
        if not self._valid(turn_id, generation) or self.current_turn_state.status != "in_progress":
            return False
        kind = event["type"]
        seq = event.get("seq")
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
        pending = copy.deepcopy(self.pending_groups)
        completed = copy.deepcopy(self.completed_groups)
        ready = None
        if kind == "model_message.done":
            mid = event["message_id"]
            if mid in completed or mid in pending:
                raise ValueError("重复的模型完整消息")
            calls = event.get("tool_calls", [])
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
            matches = [(mid, group) for mid, group in pending.items()
                       if any(call["id"] == call_id for call in group["assistant"]["tool_calls"])]
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
            self._emit(db, events, kind, turn_id, event)
            if ready:
                self._save_group(db, turn_id, *ready)
        await self._write(save)
        if ready:
            completed[ready[0]] = True
        self.pending_groups = pending
        self.completed_groups = completed
        if seq:
            self.last_agent_seq[turn_id] = seq
        return True

    def _save_group(self, db, turn_id, mid, group):
        assistant = group["assistant"]
        calls = assistant.get("tool_calls", [])
        tool_calls = [{"id": call["id"], "type": "function", "function": {"name": call["name"], "arguments": call.get("args_json", "{}")}} for call in calls]
        messages = [{"role": "assistant", "content": assistant.get("content", ""), "tool_calls_json": json.dumps(tool_calls, ensure_ascii=False)}]
        for call in calls:
            result = group["results"][call["id"]]
            content = result.get("result_json")
            if content is None:
                content = json.dumps({"error": result.get("error_message") or result["error"]}, ensure_ascii=False)
            json.loads(content)
            messages.append({"role": "tool", "content": content, "tool_call_id": call["id"], "name": call["name"]})
        sequence = db.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM chat_messages WHERE session_id=?", (self.session_id,)).fetchone()[0]
        for index, message in enumerate(messages):
            crud.create_message(db, message_id=uuid.uuid4().hex, session_id=self.session_id, turn_id=turn_id,
                                now=utc_now(), sequence=sequence + index, group_id=f"{turn_id}:{mid}",
                                group_index=index, commit=False, **message)

    async def _finish(self, turn_id, status, error=None):
        def finish(db, events):
            now = utc_now()
            row = crud.update_turn_status_if_current(db, turn_id=turn_id, current_statuses={"queued", "in_progress", "cancelling"}, status=status, now=now, completed_at=now, commit=False)
            if row is None:
                return crud.get_turn(db, turn_id)
            if status == "cancelled":
                self._emit(db, events, "turn.cancel_requested", turn_id)
            failed_preparation = self.session["status"] == "processing"
            crud.update_session(db, session_id=self.session_id, now=now, clear_active_turn=True,
                                status="failed" if failed_preparation else "ready", commit=False)
            self._emit(db, events, "turn." + status, turn_id, {"error": error})
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
        if not self.closed:
            await self._ask("ended", turn_id, generation, error)

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
        subscription = Subscription(max_events=self.settings.subscription_max_events, max_bytes=self.settings.subscription_max_bytes)
        self.subscribers[subscription.id] = subscription
        return ResumeContext(self.session_id, self.active_turn_id, self.last_event_seq, copy.deepcopy(self.session),
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
        if runtimes:
            await asyncio.gather(*(runtime.wait_closed() for runtime in runtimes), return_exceptions=True)
        await self._ask("stop")
        await self.task

    async def _handle_stop(self):
        self.closed = True
        for subscription in self.subscribers.values():
            subscription.close()
        self.subscribers.clear()
