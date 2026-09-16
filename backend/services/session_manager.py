"""会话级命令串行化：create / cancel / attach / upload / remove / replace_resources + 订阅管理。

对应 codex app-server 的 ThreadState：只拥有 session 级状态（session 行、
active_turn_id、订阅者、资源引用），turn 执行态全部在 TurnRuntime。manager 对 runtime
只有一个反向通道 cancel()；轮终态由 runtime 广播回来，cancel 的响应延迟补发。
"""

import asyncio
import copy
import io
import math
import sqlite3
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path

from backend.crud import crud
from backend.services.errors import BackendServiceError, ConflictError, NotFoundError, ValidationError
from backend.services.session_history import ResumeContext
from backend.services.subscription import Subscription
from backend.services.time_utils import utc_now
from backend.services.turn_runtime import TurnRuntime
from traceagent_shared.object_store import parse_resource_path

TERMINAL = {"completed", "cancelled", "failed"}


@dataclass
class Command:
    name: str
    args: tuple
    reply: asyncio.Future | None = None


class SessionManager:
    def __init__(self, *, session, resources, database, agent_client, document_client, settings, object_store=None):
        self.session_id = session["id"]
        self.session = session
        self.resources = resources
        self.database = database
        self.agent_client = agent_client
        self.document_client = document_client
        self.object_store = object_store
        self.settings = settings
        self.runtime = None
        self.subscribers = {}
        self.pending_cancel = None
        self.commands = asyncio.Queue(maxsize=settings.session_command_limit)
        self.closed = self.closing = self.broken = False
        self.recovery_task = None
        self.last_activity = asyncio.get_running_loop().time()
        self.task = asyncio.create_task(self._run(), name=f"session:{self.session_id}")

    @property
    def active_turn_id(self):
        return self.session["active_turn_id"]

    def fail(self):
        """事务写失败时标记 manager 损坏：清空执行态让 idle 可通过，补发挂起的
        cancel，断开订阅，并尽力把活跃轮收口为 failed 让回收重载后的会话可用。"""
        self.broken = True
        runtime, self.runtime = self.runtime, None
        if runtime is not None:
            runtime.cancel()
        turn_id = self.active_turn_id
        self.session = {**self.session, "active_turn_id": None}
        if self.pending_cancel is not None:
            pending, self.pending_cancel = self.pending_cancel, None
            if not pending.reply.done():
                pending.reply.set_result({"status": "failed"})
        for subscription in self.subscribers.values():
            subscription.close()
        self.subscribers.clear()
        self.recovery_task = asyncio.create_task(self._recover_active_turn(turn_id))

    async def _recover_active_turn(self, turn_id):
        """尽力收口：活跃轮标 failed、session 认领清空；数据库仍不可用时交给重启收口。"""
        def recover():
            db = self.database.connect()
            with crud.transaction(db):
                if turn_id is not None:
                    crud.update_turn_status_if_current(db, turn_id=turn_id,
                                                       current_statuses={"queued", "in_progress", "cancelling"},
                                                       status="failed", now=utc_now(), error="storage_failure")
                crud.update_session(db, session_id=self.session_id, now=utc_now(), clear_active_turn=True,
                                    status="ready")
        try:
            await asyncio.to_thread(recover)
        except Exception:
            pass

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

    async def broadcast(self, turn_id, event):
        """runtime 广播通道：在 runtime 任务上下文中执行，asyncio 单线程内原子。"""
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
        content = content.strip()
        if not content:
            raise ValidationError("content 不能为空")
        run_options = run_options or {}
        if set(run_options) - {"tool_execution_timeout"}:
            raise ValidationError("未知的 run_options 字段")
        timeout = run_options.get("tool_execution_timeout")
        if timeout is not None and (isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0):
            raise ValidationError("工具超时必须为有限正数")
        return await self._ask("create", content, run_options)

    async def _handle_create(self, content, run_options):
        if self.active_turn_id:
            raise ConflictError("会话已有活跃轮次")
        turn_id = uuid.uuid4().hex
        runtime = TurnRuntime(session_id=self.session_id, agent_client=self.agent_client, database=self.database,
                              refresh=self._refresh_state, publish=self._runtime_publish, fail=self.fail,
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

    def _refresh_state(self, session, resources):
        """runtime 写事务的缓存同步点：事务内快照直接成为 manager 的状态。"""
        self.session, self.resources = session, resources

    async def _runtime_publish(self, event):
        """runtime 广播通道：事务提交后逐事件转发。"""
        await self.broadcast(event["turn_id"], event)

    async def _transaction(self, operation, events):
        def execute():
            db = self.database.connect()
            with crud.transaction(db):
                result = operation(db, events)
                return result, crud.get_session(db, self.session_id), crud.list_resources(db, self.session_id)

        result, self.session, self.resources = await asyncio.to_thread(execute)
        try:
            for event in events:
                await self.broadcast(event["turn_id"], event)
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

    async def _handle_detach(self, subscription_id):
        subscription = self.subscribers.pop(subscription_id, None)
        if subscription:
            subscription.close()

    async def upload_files(self, files):
        """会话级上传：与调用方输入无关的文件形状校验在入队前完成；
        依赖会话状态的配额检查、document service 物化和资源替换作为
        一个命令在队列内执行，和其他命令严格串行，避免并发读改写。"""
        if not files:
            raise ValidationError("files 不能为空")
        self._check_file_shapes(files)
        return await self._ask("upload", files)

    def _check_file_shapes(self, files):
        filenames = set()
        for file in files:
            filename = file.get("filename") if isinstance(file, dict) else None
            content = file.get("content") if isinstance(file, dict) else None
            if not isinstance(filename, str) or not filename.strip() or "/" in filename or "\\" in filename:
                raise ValidationError("文件名不能为空且不能包含路径分隔符")
            if filename in filenames:
                raise ValidationError("同一批上传文件名重复")
            filenames.add(filename)
            if Path(filename).suffix.lower().lstrip(".") not in self.settings.supported_file_types:
                raise ValidationError("只支持 PDF/DOCX 文件")
            if not isinstance(content, bytes) or not content:
                raise ValidationError("文件内容不能为空")

    async def _handle_upload(self, files):
        """基于当前会话状态校验配额 -> document service 物化重建 -> 原子替换资源引用。"""
        raw_rows = [row for row in self.resources if row["type"] == "raw"]
        if len(raw_rows) + len(files) > self.settings.upload_max_files:
            raise ValidationError("会话文件数超过限制")
        total = sum(row["size_bytes"] for row in raw_rows) + sum(len(file["content"]) for file in files)
        if total > self.settings.upload_max_bytes:
            raise ValidationError("会话资源总量超过限制")
        refs = await self.document_client.prepare_resources(session_id=self.session_id, files=files)
        return await self._replace_resources(refs, self._raw_sizes(refs, files))

    async def remove_file(self, resource_id):
        """删除会话里的原始文件：document service 排除 raw 并重建 bundle，再替换资源引用。"""
        return await self._ask("remove", resource_id)

    async def _handle_remove(self, resource_id):
        row = crud.get_resource(self.database.connect(), resource_id)
        if row is None or row["session_id"] != self.session_id:
            raise NotFoundError("资源不存在")
        if row["type"] != "raw":
            raise ValidationError("只能删除原始文件")
        refs = await self.document_client.prepare_resources(
            session_id=self.session_id, files=[],
            remove_raw=[{"type": row["type"], "location": row["location"]}])
        return await self._replace_resources(refs, {})

    @staticmethod
    def _raw_sizes(refs, files):
        """把上传文件大小按 raw/<filename> 后缀对齐到 agent 返回的 raw 引用。"""
        sizes = {}
        for file in files:
            for ref in refs:
                if ref["type"] == "raw" and ref["location"].endswith(f"/raw/{file['filename']}"):
                    sizes[ref["location"]] = len(file["content"])
        return sizes

    async def read_block(self, key):
        """读取会话文档归档内段落原文，供前端回溯引用；bucket 取自本会话的
        documents 引用，跨会话读不到对方的桶。"""
        documents = next((row for row in self.resources if row["type"] == "documents"), None)
        if documents is None:
            raise NotFoundError("会话没有文档归档")
        bucket = documents["location"].removeprefix("s3://").partition("/")[0]
        blocks = await self.document_client.read_blocks(bucket=bucket, keys=[key])
        if not blocks or not blocks[0]["found"]:
            raise NotFoundError("段落不存在")
        return blocks[0]

    def _documents_location(self):
        """本会话 documents 引用的 s3:// 定位；没有归档的会话直接拒绝。"""
        documents = next((row for row in self.resources if row["type"] == "documents"), None)
        if documents is None:
            raise NotFoundError("会话没有文档归档")
        return documents["location"]

    def _store(self):
        """读取通道的对象存储访问；未显式注入时按环境构造。"""
        from traceagent_shared.object_store import build_s3_object_store
        return self.object_store if self.object_store is not None else build_s3_object_store()

    async def download_file(self, resource_id):
        """读取会话原始文件字节，供前端下载；资源行归属与类型在这里校验。"""
        row = crud.get_resource(self.database.connect(), resource_id)
        if row is None or row["session_id"] != self.session_id:
            raise NotFoundError("资源不存在")
        if row["type"] != "raw":
            raise ValidationError("只能下载原始文件")
        bucket, key = parse_resource_path(row["location"])
        data = await asyncio.to_thread(lambda: self._store().get_object(bucket, key))
        if data is None:
            raise NotFoundError("文件不存在")
        return row, data

    async def list_documents(self):
        """列出会话归档内的处理后 md 文件（key 与大小），供前端浏览文档树。"""
        bucket, archive_key = parse_resource_path(self._documents_location())
        archive = await asyncio.to_thread(lambda: self._store().get_object(bucket, archive_key))
        if archive is None:
            raise NotFoundError("会话没有文档归档")
        with zipfile.ZipFile(io.BytesIO(archive)) as members:
            return [{"key": info.filename, "size": info.file_size} for info in members.infolist()
                    if not info.is_dir()]

    async def read_document(self, key):
        """读取会话归档内单个 md 文件全文，供前端查看处理后文档。"""
        bucket = parse_resource_path(self._documents_location())[0]
        blocks = await self.document_client.read_blocks(bucket=bucket, keys=[key])
        if not blocks or not blocks[0]["found"]:
            raise NotFoundError("文档不存在")
        return {"key": key, "text": blocks[0]["text"]}

    async def replace_resources(self, refs, sizes):
        return await self._ask("replace_resources", refs, sizes)

    async def _handle_replace_resources(self, refs, sizes):
        return await self._replace_resources(refs, sizes)

    async def _replace_resources(self, refs, sizes):
        """以 agent 返回的全量 refs 替换会话资源；raw 尺寸优先取本次上传，未变的沿用旧值。"""
        old_sizes = {row["location"]: row["size_bytes"] for row in self.resources if row["type"] == "raw"}

        def replace(db, events):
            now = utc_now()
            crud.delete_resources(db, self.session_id)
            for ref in refs:
                crud.create_resource(db, resource_id=uuid.uuid4().hex, session_id=self.session_id,
                                     resource_type=ref["type"], location=ref["location"], now=now,
                                     size_bytes=int(sizes.get(ref["location"], old_sizes.get(ref["location"], 0))))
            events.append({"type": "resources.prepared", "turn_id": None,
                           "payload": {"resources": [{"type": ref["type"], "location": ref["location"]}
                                                     for ref in refs if ref["type"] != "raw"]}})

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
        if self.recovery_task is not None:
            await asyncio.gather(self.recovery_task, return_exceptions=True)
        await self.commands.put(Command("stop", (), asyncio.get_running_loop().create_future()))
        await self.task

    async def _handle_stop(self):
        self.closed = True
        for subscription in self.subscribers.values():
            subscription.close()
        self.subscribers.clear()
