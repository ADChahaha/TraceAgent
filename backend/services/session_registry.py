"""进程级会话注册表：启动恢复、唯一加载、请求去重与空闲回收。"""

import asyncio
import hashlib
import json
import math
import uuid
from pathlib import Path

from backend.core.db import transaction
from backend.crud import crud
from backend.services.errors import ConflictError, NotFoundError, ValidationError, BackendServiceError
from backend.services.session_manager import SessionManager
from backend.services.time_utils import utc_now


class SessionRegistry:
    def __init__(self, *, database, agent_client, settings):
        self.database = database
        self.agent_client = agent_client
        self.settings = settings
        self.managers = {}
        self.loading = {}
        self.lock = asyncio.Lock()
        self.creation_lock = asyncio.Lock()
        self.closed = False
        self.reaper = None
        self.requests = set()
        self.cleanup_tasks = set()

    async def start(self):
        def recover():
            db = self.database.connect()
            with transaction(db):
                sessions = db.execute("SELECT * FROM chat_sessions WHERE active_turn_id IS NOT NULL OR status IN ('processing','running')").fetchall()
                for session in sessions:
                    now = utc_now()
                    turns = db.execute("SELECT id FROM chat_turns WHERE session_id=? AND status IN ('queued','in_progress','cancelling')", (session["id"],)).fetchall()
                    for turn in turns:
                        crud.update_turn(db, turn_id=turn["id"], now=now, status="failed", completed_at=now, commit=False)
                        crud.create_event(db, event_id=uuid.uuid4().hex, session_id=session["id"], turn_id=turn["id"],
                                          event_type="turn.failed", payload={"error": "backend_restarted"}, now=now, commit=False)
                    crud.update_session(db, session_id=session["id"], now=now, clear_active_turn=True,
                                        status="failed" if session["status"] == "processing" else "ready", commit=False)
        await asyncio.to_thread(recover)
        self.reaper = asyncio.create_task(self._reap_loop(), name="session-reaper")

    async def _load(self, session_id):
        def read():
            db = self.database.connect()
            session = crud.get_session(db, session_id)
            if session is None:
                raise NotFoundError("会话不存在")
            return session, crud.list_resources(db, session_id), crud.get_last_event_sequence(db, session_id)
        try:
            session, resources, seq = await asyncio.to_thread(read)
            manager = SessionManager(session=session, resources=resources, last_event_seq=seq,
                                     database=self.database, agent_client=self.agent_client, settings=self.settings)
            async with self.lock:
                closing = self.closed
                if not closing:
                    self.managers[session_id] = manager
            if closing:
                await manager.close()
                raise BackendServiceError("服务正在关闭")
            return manager
        finally:
            async with self.lock:
                if self.loading.get(session_id) is asyncio.current_task():
                    self.loading.pop(session_id, None)

    async def get_or_load(self, session_id):
        async with self.lock:
            if self.closed:
                raise BackendServiceError("服务正在关闭")
            manager = self.managers.get(session_id)
            if manager:
                manager.last_activity = asyncio.get_running_loop().time()
                return manager
            task = self.loading.get(session_id)
            if task is None:
                task = asyncio.create_task(self._load(session_id))
                task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
                self.loading[session_id] = task
        try:
            manager = await asyncio.shield(task)
        except BaseException:
            if task.done():
                async with self.lock:
                    if self.loading.get(session_id) is task:
                        self.loading.pop(session_id, None)
            raise
        async with self.lock:
            manager.last_activity = asyncio.get_running_loop().time()
        return manager

    async def complete(self, **params):
        # 浏览器断开不释放受理中的幂等锁；backend 持有整段受理任务。
        task = asyncio.create_task(self._complete(**params), name="accept-completion")
        self.requests.add(task)
        task.add_done_callback(self.requests.discard)
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            def cleanup(done):
                if done.cancelled() or done.exception() is not None:
                    return
                manager, context = done.result()
                context.subscription.close()
                released = asyncio.create_task(manager.detach(context.subscription.id))
                self.cleanup_tasks.add(released)
                released.add_done_callback(self.cleanup_tasks.discard)
            task.add_done_callback(cleanup)
            raise

    async def _complete(self, *, content, session_id=None, files=None, run_options=None, request_id=None):
        if not isinstance(content, str) or not content.strip():
            raise ValidationError("content 不能为空")
        files = files or []
        run_options = run_options or {}
        if set(run_options) - {"tool_execution_timeout"}:
            raise ValidationError("未知的 run_options 字段")
        timeout = run_options.get("tool_execution_timeout")
        if timeout is not None and (isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0):
            raise ValidationError("工具超时必须为有限正数")
        if request_id is not None and (not isinstance(request_id, str) or not request_id.strip() or len(request_id) > 200):
            raise ValidationError("request_id 必须是 1–200 字符的非空字符串")
        if len(files) > self.settings.upload_max_files or sum(len(f["content"]) for f in files) > self.settings.upload_max_bytes:
            raise ValidationError("上传文件超过限制")
        for file in files:
            if Path(file["filename"]).suffix.lower().lstrip(".") not in self.settings.supported_file_types:
                raise ValidationError("只支持 PDF/DOCX 文件")
        content = content.strip()
        fingerprint = hashlib.sha256(json.dumps({"content": content, "session_id": session_id, "run_options": run_options,
            "files": [(f["filename"], hashlib.sha256(f["content"]).hexdigest()) for f in files]},
            sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        # 单进程创建入口串行：同一个请求即使尚不知道 session_id，也只接受一次。
        async with self.creation_lock:
            if self.closed:
                raise BackendServiceError("服务正在关闭")
            if request_id:
                def lookup():
                    row = self.database.connect().execute(
                        "SELECT session_id,turn_id,payload_json FROM chat_events "
                        "WHERE event_type='turn.created' AND json_extract(payload_json,'$.request_id')=? LIMIT 1", (request_id,)).fetchone()
                    return dict(row) if row else None
                row = await asyncio.to_thread(lookup)
                if row:
                    if json.loads(row["payload_json"])["fingerprint"] != fingerprint:
                        raise ConflictError("request_id 已用于不同请求")
                    manager = await self.get_or_load(row["session_id"])
                    context = await manager.attach()
                    context.turn_id = row["turn_id"]
                    return manager, context
            if session_id is None:
                session_id = uuid.uuid4().hex
                def create():
                    crud.create_session(self.database.connect(), session_id=session_id, status="ready", now=utc_now())
                await asyncio.to_thread(create)
            manager = await self.get_or_load(session_id)
            context = await manager.create_completion(content=content, files=files, run_options=run_options,
                                                       request_id=request_id, fingerprint=fingerprint)
            return manager, context

    async def evict_idle(self):
        async with self.creation_lock:
            async with self.lock:
                now = asyncio.get_running_loop().time()
                for key, manager in list(self.managers.items()):
                    if manager.idle() and now - manager.last_activity >= self.settings.session_idle_seconds:
                        await manager.close()
                        if self.managers.get(key) is manager:
                            self.managers.pop(key)

    async def _reap_loop(self):
        while True:
            await asyncio.sleep(min(10, self.settings.session_idle_seconds))
            await self.evict_idle()

    async def close(self):
        self.closed = True
        if self.reaper:
            self.reaper.cancel()
            await asyncio.gather(self.reaper, return_exceptions=True)
        await asyncio.gather(*list(self.requests), return_exceptions=True)
        await asyncio.gather(*list(self.cleanup_tasks), return_exceptions=True)
        async with self.creation_lock:
            pending = list(self.loading.values())
            loaded = await asyncio.gather(*pending, return_exceptions=True)
            managers = set(self.managers.values()) | {m for m in loaded if isinstance(m, SessionManager)}
            await asyncio.gather(*(manager.close() for manager in managers))
            self.managers.clear()
            self.loading.clear()
