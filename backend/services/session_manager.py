"""会话级命令串行化：create / cancel / attach / detach + 订阅管理与资源操作组合。

对应 codex app-server 的 ThreadState：只拥有 session 级状态（session 行、
active_turn_id、订阅者、资源引用），turn 执行态全部在 TurnRuntime。manager 对 runtime
只有一个反向通道 cancel()；轮终态由 runtime 广播回来，cancel 的响应延迟补发。
"""

from __future__ import annotations

import asyncio
import copy
import sqlite3
import uuid
from dataclasses import dataclass

from traceagent_shared.object_store import ObjectStore

from backend.crud import crud
from backend.services.errors import BackendServiceError, ConflictError, NotFoundError
from backend.services.protocols import AgentGateway, DatabaseProtocol, DocumentGateway
from backend.services.session_history import ResumeContext
from backend.services.session_resource_mixin import SessionResourceMixin
from backend.services.session_title_worker import (
    collect_raw_filenames,
    generate_and_persist_title,
    recover_active_turn,
    validate_completion_input,
)
from backend.services.subscription import Subscription
from backend.services.turn_runtime import TurnRuntime

TERMINAL = {"completed", "cancelled", "failed"}


@dataclass
class Command:
    name: str
    args: tuple
    reply: asyncio.Future | None = None


class SessionManager(SessionResourceMixin):
    def __init__(self, *, session, resources, database: DatabaseProtocol, agent_client: AgentGateway,
                 document_client: DocumentGateway, settings, object_store: ObjectStore | None = None):
        self.session_id, self.session, self.resources = session["id"], session, resources
        self.database, self.agent_client, self.document_client = database, agent_client, document_client
        self.object_store, self.settings = object_store, settings
        self.runtime = self.pending_cancel = self.recovery_task = None
        self.subscribers = {}
        self.commands = asyncio.Queue(maxsize=settings.session_command_limit)
        self.closed = self.closing = self.broken = False
        self._title_task: asyncio.Task | None = None
        self._title_requested = bool((session.get("title") or "").strip())
        self._background_tasks: set[asyncio.Task] = set()
        self.last_activity = asyncio.get_running_loop().time()
        self.task = asyncio.create_task(self._run(), name=f"session:{self.session_id}")

    @property
    def active_turn_id(self):
        return self.session["active_turn_id"]

    def _track_task(self, task):
        if task is None or task.done():
            return
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    def fail(self):
        """事务写失败时标记 manager 损坏：清空执行态、补发挂起 cancel、断开订阅并尽力收口。"""
        self.broken = True
        runtime, self.runtime = self.runtime, None
        if runtime is not None:
            runtime.cancel()
            self._track_task(runtime.task)
        if self._title_task is not None and not self._title_task.done():
            self._title_task.cancel()
        turn_id = self.active_turn_id
        self.session = {**self.session, "active_turn_id": None}
        if self.pending_cancel is not None:
            pending, self.pending_cancel = self.pending_cancel, None
            if not pending.reply.done():
                pending.reply.set_result({"status": "failed"})
        for subscription in self.subscribers.values():
            subscription.close()
        self.subscribers.clear()
        if self.recovery_task is None or self.recovery_task.done():
            self.recovery_task = asyncio.create_task(recover_active_turn(self.database, self.session_id, turn_id))
            self._track_task(self.recovery_task)

    def _recycle_subscription(self, result):
        if isinstance(result, ResumeContext):
            result.subscription.close()
            self.subscribers.pop(result.subscription.id, None)

    async def _ask(self, name, *args):
        if self.closed or (self.closing and name != "cancel"):
            raise BackendServiceError("会话管理器已关闭")
        reply = asyncio.get_running_loop().create_future()
        try:
            self.commands.put_nowait(Command(name, args, reply))
        except asyncio.QueueFull:
            raise BackendServiceError("会话命令队列繁忙") from None
        try:
            return await reply
        except asyncio.CancelledError:
            if reply.done() and not reply.cancelled() and reply.exception() is None:
                self._recycle_subscription(reply.result())
            raise

    async def _run(self):
        while True:
            command = await self.commands.get()
            self.last_activity = asyncio.get_running_loop().time()
            try:
                if self.broken and command.name not in {"detach", "stop"}:
                    raise BackendServiceError("会话存储异常，请恢复服务后重试")
                result = await getattr(self, "_handle_" + command.name)(*command.args)
            except Exception as exc:
                if isinstance(exc, sqlite3.Error):
                    self.fail()
                if command.reply is not None and not command.reply.done():
                    command.reply.set_exception(exc)
            else:
                if command.reply is not None:
                    if command.reply.cancelled():
                        self._recycle_subscription(result)
                    elif not command.reply.done():
                        command.reply.set_result(result)
            finally:
                self.commands.task_done()
            if command.name == "stop":
                return

    async def broadcast(self, turn_id, event):
        for key, subscription in list(self.subscribers.items()):
            if not subscription.publish(event):
                self.subscribers.pop(key, None)
        if event["type"] not in {"turn.completed", "turn.failed", "turn.cancelled"}:
            return
        if self.active_turn_id == turn_id:
            self.session = {**self.session, "active_turn_id": None}
        self.runtime = None
        if self.pending_cancel is not None and self.pending_cancel.args[0] == turn_id:
            self.pending_cancel.reply.set_result({"status": event["type"].split(".")[1]})
            self.pending_cancel = None
        if self.closing:
            self.closed = True
            for subscription in self.subscribers.values():
                subscription.close()
            self.subscribers.clear()

    async def create_completion(self, *, content, run_options=None):
        cleaned, options = validate_completion_input(content, run_options)
        return await self._ask("create", cleaned, options)

    def _new_subscription(self) -> Subscription:
        subscription = Subscription(
            max_events=self.settings.subscription_max_events,
            max_bytes=self.settings.subscription_max_bytes,
        )
        self.subscribers[subscription.id] = subscription
        return subscription

    async def _handle_create(self, content, run_options):
        if self.active_turn_id:
            raise ConflictError("会话已有活跃轮次")
        turn_id = uuid.uuid4().hex
        runtime = TurnRuntime(
            session_id=self.session_id, agent_client=self.agent_client, database=self.database,
            refresh=self._refresh_state, publish=self._runtime_publish, fail=self.fail,
            turn_id=turn_id, content=content, run_options=run_options,
        )
        self.runtime = runtime
        runtime.start()
        await runtime.begun.wait()
        if runtime.begin_error is not None:
            raise runtime.begin_error
        turn_ids = await asyncio.to_thread(
            lambda: [turn["id"] for turn in crud.list_turns(self.database.connect(), self.session_id)])
        subscription = self._new_subscription()
        self._maybe_start_title_generation(content)
        return ResumeContext(
            self.session_id, turn_id, turn_ids, copy.deepcopy(self.session),
            copy.deepcopy(self.resources), runtime.snapshot(), subscription,
            self.settings.snapshot_max_bytes,
        )

    def _maybe_start_title_generation(self, question: str) -> None:
        if self._title_requested or (self.session.get("title") or "").strip():
            return
        self._title_requested = True

        async def on_persisted(new_title: str) -> None:
            self.session = {**self.session, "title": new_title}
            await self.broadcast(None, {"turn_id": None, "type": "session.updated", "payload": {"title": new_title}})

        self._title_task = asyncio.create_task(
            generate_and_persist_title(
                session_id=self.session_id, question=question, filenames=collect_raw_filenames(self.resources),
                agent_client=self.agent_client, database=self.database,
                timeout_seconds=self.settings.title_generation_timeout_seconds,
                is_inactive=lambda: self.closed or self.closing or self.broken, on_persisted=on_persisted,
            ),
            name=f"title:{self.session_id}",
        )
        self._track_task(self._title_task)

    def _merge_session_state(self, session):
        existing = (self.session.get("title") or "").strip() if self.session else ""
        incoming = (session.get("title") or "").strip() if session else ""
        return {**session, "title": existing} if existing and not incoming else session

    def _refresh_state(self, session, resources):
        self.session, self.resources = self._merge_session_state(session), resources

    async def _runtime_publish(self, event):
        await self.broadcast(event["turn_id"], event)

    async def _transaction(self, operation, events):
        def execute():
            db = self.database.connect()
            with crud.transaction(db):
                result = operation(db, events)
                return result, crud.get_session(db, self.session_id), crud.list_resources(db, self.session_id)

        result, session, self.resources = await asyncio.to_thread(execute)
        self.session = self._merge_session_state(session)
        try:
            for event in events:
                await self.broadcast(event["turn_id"], event)
        except Exception:
            self.fail()
            raise
        return result

    async def cancel(self, turn_id): return await self._ask("cancel", turn_id)
    async def attach(self): return await self._ask("attach")

    async def detach(self, subscription_id):
        if not self.closed:
            await self._ask("detach", subscription_id)

    async def _handle_cancel(self, turn_id):
        row = crud.get_turn(self.database.connect(), turn_id)
        if row is None or row["session_id"] != self.session_id:
            raise NotFoundError("轮次不存在")
        if row["status"] in TERMINAL:
            return row
        if self.active_turn_id != turn_id:
            raise ConflictError("该轮次不是当前活跃轮次")
        self.pending_cancel = Command("cancel", (turn_id,), asyncio.get_running_loop().create_future())
        if self.runtime is not None:
            self.runtime.cancel()
        return await self.pending_cancel.reply

    async def _handle_attach(self):
        turn_ids = await asyncio.to_thread(
            lambda: [turn["id"] for turn in crud.list_turns(self.database.connect(), self.session_id)])
        subscription = self._new_subscription()
        current = self.runtime.snapshot() if self.runtime is not None and self.runtime.status == "queued" else None
        return ResumeContext(
            self.session_id, self.active_turn_id, turn_ids, copy.deepcopy(self.session),
            copy.deepcopy(self.resources), current, subscription, self.settings.snapshot_max_bytes,
        )

    async def _handle_detach(self, subscription_id):
        subscription = self.subscribers.pop(subscription_id, None)
        if subscription:
            subscription.close()

    def idle(self):
        return self.active_turn_id is None and self.runtime is None and not self.subscribers and self.commands.empty()

    async def _drain_background_tasks(self):
        while True:
            runtime, self.runtime = self.runtime, None
            if runtime is not None:
                runtime.cancel()
                self._track_task(runtime.task)
            if self._title_task is not None and not self._title_task.done():
                self._title_task.cancel()
            if not self._background_tasks:
                return
            await asyncio.gather(*list(self._background_tasks), return_exceptions=True)

    async def close(self):
        if self.closed:
            return
        self.closing = True
        await self._drain_background_tasks()
        if not self.task.done():
            await self.commands.put(Command("stop", (), asyncio.get_running_loop().create_future()))
        await self.task
        await self._drain_background_tasks()

    async def _handle_stop(self):
        self.closed = True
        for subscription in self.subscribers.values():
            subscription.close()
        self.subscribers.clear()
