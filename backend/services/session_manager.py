"""会话级命令串行化：create / cancel / attach / get_file / replace_resources + 订阅管理。

对应 codex app-server 的 ThreadState：只拥有 session 级状态（session 行、
active_turn_id、订阅者、资源引用），turn 执行态全部在 TurnRuntime。manager 对 runtime
只有一个反向通道 cancel()；轮终态由 runtime 广播回来，cancel 的响应延迟补发。
"""

import asyncio
import copy
import sqlite3
import uuid
from dataclasses import dataclass

from backend.crud import crud
from backend.services.errors import BackendServiceError, ConflictError, NotFoundError, ValidationError
from backend.services.session_history import ResumeContext
from backend.services.subscription import Subscription
from backend.services.time_utils import utc_now
from backend.services.turn_runtime import TurnRuntime

TERMINAL = {"completed", "cancelled", "failed"}


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
        self.runtime = None
        self.subscribers = {}
        self.pending_cancel = None
        self.commands = asyncio.Queue(maxsize=settings.session_command_limit)
        self.closed = self.closing = self.broken = False
        self.last_activity = asyncio.get_running_loop().time()
        self.task = asyncio.create_task(self._run(), name=f"session:{self.session_id}")

    @property
    def active_turn_id(self):
        return self.session["active_turn_id"]

    def fail(self):
        """runtime 事务失败时标记 manager 损坏：拒绝后续命令并断开订阅。"""
        self.broken = True
        if self.runtime is not None:
            self.runtime.cancel()
        for subscription in self.subscribers.values():
            subscription.close()

    def _recycle_subscription(self, result):
        if isinstance(result, ResumeContext):
            result.subscription.close()
            self.subscribers.pop(result.subscription.id, None)

    async def _ask(self, name, *args):
        if self.closed or (self.closing and name != "cancel"):
            raise BackendServiceError("会话管理器已关闭")
        reply = asyncio.get_running_loop().create_future()
        command = Command(name, args, reply)
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

    async def _run(self):
        while True:
            command = await self.commands.get()
            self.last_activity = asyncio.get_running_loop().time()
            try:
                if self.broken and command.name != "detach":
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
                        self._recycle_subscription(result)  # 调用方已取消，回收 handler 产生的订阅
                    elif not command.reply.done():
                        command.reply.set_result(result)
            finally:
                self.commands.task_done()
            if command.name == "stop":
                return

    def _complete_pending_cancel(self):
        """cancel 命令处理完后，若 runtime 已广播终态则补发响应。"""
        if self.pending_cancel is None or self.pending_cancel.reply.done():
            return
        turn_id = self.pending_cancel.args[0]
        if self.runtime is None or self.runtime.turn_id != turn_id or self.runtime.status != "queued":
            self.pending_cancel.reply.set_result({"status": "cancelled"})

    async def broadcast(self, turn_id, event):
        """runtime 广播通道：在 runtime 任务上下文中执行，asyncio 单线程内原子。"""
        terminal = event["type"] in {"turn.completed", "turn.failed", "turn.cancelled"}
        if terminal:
            for key, subscription in list(self.subscribers.items()):
                if not subscription.publish(event):
                    self.subscribers.pop(key, None)
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
        else:
            for key, subscription in list(self.subscribers.items()):
                if not subscription.publish(event):
                    self.subscribers.pop(key, None)

    async def create_completion(self, *, content, run_options):
        return await self._ask("create", content, run_options)

    async def _handle_create(self, content, run_options):
        if self.active_turn_id:
            raise ConflictError("会话已有活跃轮次")
        turn_id = uuid.uuid4().hex
        runtime = TurnRuntime(session_id=self.session_id, agent_client=self.agent_client,
                              write=self._runtime_commit, publish=self._runtime_publish, fail=self.fail,
                              turn_id=turn_id, content=content, run_options=run_options)
        self.runtime = runtime
        runtime.start()
        # 等 runtime 的 begin 事务提交：建轮+用户消息+认领 active_turn_id 同事务持久化后，
        # 命令才返回。响应先于提交会打开丢消息窗口；不等待则并发 create 会双建轮。
        await runtime.begun.wait()
        if runtime.begin_error is not None:
            raise runtime.begin_error
        subscription = Subscription(max_events=self.settings.subscription_max_events, max_bytes=self.settings.subscription_max_bytes)
        self.subscribers[subscription.id] = subscription
        return ResumeContext(self.session_id, turn_id, [turn_id], copy.deepcopy(self.session),
                             copy.deepcopy(self.resources), runtime.snapshot(), subscription,
                             self.settings.snapshot_max_bytes)

    async def _runtime_commit(self, operation, events):
        """runtime 写通道：开事务执行并刷新 session/resources 缓存；失败标记损坏。"""
        def execute():
            db = self.database.connect()
            with crud.transaction(db):
                result = operation(db, events)
                return result, crud.get_session(db, self.session_id), crud.list_resources(db, self.session_id)

        try:
            result, self.session, self.resources = await asyncio.to_thread(execute)
        except Exception:
            self.fail()
            raise
        return result

    async def _runtime_publish(self, event):
        """runtime 广播通道：事务提交后逐事件转发；失败标记损坏。"""
        try:
            await self.broadcast(event["turn_id"], event)
        except Exception:
            self.fail()
            raise

    async def _transaction(self, operation, events):
        def execute():
            db = self.database.connect()
            with crud.transaction(db):
                result = operation(db, events)
                return result, crud.get_session(db, self.session_id), crud.list_resources(db, self.session_id)

        result, self.session, self.resources = await asyncio.to_thread(execute)
        try:
            for event in events:
                for key, subscription in list(self.subscribers.items()):
                    if not subscription.publish(event):
                        self.subscribers.pop(key, None)
        except Exception:
            self.fail()
            raise
        return result

    async def cancel(self, turn_id):
        return await self._ask("cancel", turn_id)

    async def _handle_cancel(self, turn_id):
        row = crud.get_turn(self.database.connect(), turn_id)
        if row is None or row["session_id"] != self.session_id:
            raise NotFoundError("轮次不存在")
        if row["status"] in TERMINAL:
            return row
        if self.active_turn_id != turn_id:
            raise ConflictError("该轮次不是当前活跃轮次")
        # 登记等待者并发出取消信号；响应在 runtime 广播终态后补发（pending_cancel 模式）。
        self.pending_cancel = Command("cancel", (turn_id,), asyncio.get_running_loop().create_future())
        if self.runtime is not None:
            self.runtime.cancel()
        return await self.pending_cancel.reply

    async def attach(self):
        return await self._ask("attach")

    async def _handle_attach(self):
        turn_ids = await asyncio.to_thread(
            lambda: [turn["id"] for turn in crud.list_turns(self.database.connect(), self.session_id)])
        subscription = Subscription(max_events=self.settings.subscription_max_events, max_bytes=self.settings.subscription_max_bytes)
        self.subscribers[subscription.id] = subscription
        return ResumeContext(self.session_id, self.active_turn_id, turn_ids, copy.deepcopy(self.session),
                             copy.deepcopy(self.resources),
                             self.runtime.snapshot() if self.runtime is not None and self.runtime.status == "queued" else None,
                             subscription, self.settings.snapshot_max_bytes)

    async def detach(self, subscription_id):
        if not self.closed:
            await self._ask("detach", subscription_id)

    async def get_file(self, resource_id):
        return await self._ask("get_file", resource_id)

    async def _handle_get_file(self, resource_id):
        row = crud.get_resource(self.database.connect(), resource_id)
        if row is None or row["session_id"] != self.session_id:
            raise NotFoundError("资源不存在")
        if row["type"] != "raw":
            raise ValidationError("只能删除原始文件")
        return row

    async def replace_resources(self, refs, sizes):
        return await self._ask("replace_resources", refs, sizes)

    async def _handle_replace_resources(self, refs, sizes):
        """以 agent 返回的全量 refs 替换会话资源；raw 尺寸优先取本次上传，未变的沿用旧值。"""
        old_sizes = {row["location"]: row["size_bytes"] for row in self.resources if row["type"] == "raw"}

        def replace(db, events):
            now = utc_now()
            crud.delete_resources(db, self.session_id, commit=False)
            for ref in refs:
                crud.create_resource(db, resource_id=uuid.uuid4().hex, session_id=self.session_id,
                                     resource_type=ref["type"], location=ref["location"], now=now,
                                     size_bytes=int(sizes.get(ref["location"], old_sizes.get(ref["location"], 0))),
                                     commit=False)
            events.append({"type": "resources.prepared", "turn_id": None,
                           "payload": {"resources": [{"type": ref["type"], "location": ref["location"]} for ref in refs]}})

        await self._transaction(replace, [])
        return self.resources

    async def _handle_detach(self, subscription_id):
        subscription = self.subscribers.pop(subscription_id, None)
        if subscription:
            subscription.close()

    def idle(self):
        return self.active_turn_id is None and self.runtime is None and not self.subscribers and self.commands.empty()

    async def close(self):
        if self.closed:
            return
        self.closing = True
        if self.runtime is not None and not self.broken:
            self.runtime.cancel()
            await self.runtime.wait_closed()
        await self.commands.put(Command("stop", (), asyncio.get_running_loop().create_future()))
        await self.task

    async def _handle_stop(self):
        self.closed = True
        for subscription in self.subscribers.values():
            subscription.close()
        self.subscribers.clear()
