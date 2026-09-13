"""进程级会话注册表：启动恢复、Manager 生命周期状态机、空闲回收。

全局锁只保护 entries 的查询与状态转换；真实加载、关闭都在锁外执行。
"""

import asyncio
import math
import uuid
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path

from backend.crud import crud
from backend.services.errors import ConflictError, NotFoundError, ValidationError
from backend.services.session_manager import SessionManager
from backend.services.time_utils import utc_now


class ManagerState(Enum):
    CREATING = auto()
    READY = auto()
    CLOSING = auto()


@dataclass
class Entry:
    state: ManagerState
    manager: SessionManager | None = None


class SessionRegistry:
    def __init__(self, *, database, agent_client, settings):
        self.database = database
        self.agent_client = agent_client
        self.settings = settings
        self.entries = {}
        self.lock = asyncio.Lock()
        self.reaper = None

    async def start(self):
        def recover():
            db = self.database.connect()
            with crud.transaction(db):
                sessions = crud.list_sessions_needing_recovery(db)
                for session in sessions:
                    now = utc_now()
                    turns = crud.list_unfinished_turns(db, session["id"])
                    for turn in turns:
                        crud.update_turn(db, turn_id=turn["id"], now=now, status="failed", error="backend_restarted",
                                         completed_at=now, commit=False)
                    crud.update_session(db, session_id=session["id"], now=now, clear_active_turn=True,
                                        status="failed" if session["status"] == "processing" else "ready", commit=False)
        await asyncio.to_thread(recover)
        self.reaper = asyncio.create_task(self._reap_loop(), name="session-reaper")

    async def get_or_begin_create(self, session_id):
        """READY 返回现有 manager；不存在则写入 CREATING 并返回 None 表示取得创建权。"""
        async with self.lock:
            entry = self.entries.get(session_id)
            if entry is None:
                self.entries[session_id] = Entry(state=ManagerState.CREATING)
                return None
            if entry.state is ManagerState.CREATING:
                raise ConflictError("会话正在初始化")
            if entry.state is ManagerState.CLOSING:
                raise ConflictError("会话正在关闭")
            entry.manager.last_activity = asyncio.get_running_loop().time()
            return entry.manager

    async def finish_create(self, session_id, manager):
        async with self.lock:
            entry = self.entries.get(session_id)
            if entry is None or entry.state is not ManagerState.CREATING:
                raise RuntimeError("非法 Manager 生命周期状态")
            entry.state = ManagerState.READY
            entry.manager = manager

    async def abort_create(self, session_id):
        async with self.lock:
            entry = self.entries.get(session_id)
            if entry is not None and entry.state is ManagerState.CREATING:
                self.entries.pop(session_id, None)

    async def get(self, session_id):
        """只获取现有 manager，不触发加载、不修改生命周期状态。"""
        async with self.lock:
            entry = self.entries.get(session_id)
            if entry is None:
                raise NotFoundError("会话不存在")
            if entry.state is ManagerState.CREATING:
                raise ConflictError("会话正在初始化")
            if entry.state is ManagerState.CLOSING:
                raise ConflictError("会话正在关闭")
            entry.manager.last_activity = asyncio.get_running_loop().time()
            return entry.manager

    async def get_or_create(self, session_id):
        """READY 直接复用；不存在时由当前请求负责加载并在锁外完成。"""
        manager = await self.get_or_begin_create(session_id)
        if manager is not None:
            return manager
        created = None
        try:
            created = await self._load_manager(session_id)
            await self.finish_create(session_id, created)
            return created
        except BaseException:
            try:
                if created is not None:
                    await created.close()
            finally:
                await self.abort_create(session_id)
            raise

    async def _load_manager(self, session_id):
        def read():
            db = self.database.connect()
            session = crud.get_session(db, session_id)
            if session is None:
                raise NotFoundError("会话不存在")
            return session, crud.list_resources(db, session_id)
        session, resources = await asyncio.to_thread(read)
        return SessionManager(session=session, resources=resources,
                              database=self.database, agent_client=self.agent_client, settings=self.settings)

    def _create_session(self, session_id):
        crud.create_session(self.database.connect(), session_id=session_id, status="ready", now=utc_now())

    async def complete(self, *, content, session_id=None, files=None, run_options=None):
        if not isinstance(content, str) or not content.strip():
            raise ValidationError("content 不能为空")
        files = files or []
        run_options = run_options or {}
        if set(run_options) - {"tool_execution_timeout"}:
            raise ValidationError("未知的 run_options 字段")
        timeout = run_options.get("tool_execution_timeout")
        if timeout is not None and (isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0):
            raise ValidationError("工具超时必须为有限正数")
        if len(files) > self.settings.upload_max_files or sum(len(f["content"]) for f in files) > self.settings.upload_max_bytes:
            raise ValidationError("上传文件超过限制")
        for file in files:
            if Path(file["filename"]).suffix.lower().lstrip(".") not in self.settings.supported_file_types:
                raise ValidationError("只支持 PDF/DOCX 文件")
        content = content.strip()
        if session_id is None:
            session_id = uuid.uuid4().hex
            await asyncio.to_thread(self._create_session, session_id)
        manager = await self.get_or_create(session_id)
        context = await manager.create_completion(content=content, files=files, run_options=run_options)
        return manager, context

    async def evict_idle(self):
        closing = []
        async with self.lock:
            now = asyncio.get_running_loop().time()
            for key, entry in list(self.entries.items()):
                if entry.state is not ManagerState.READY or entry.manager is None:
                    continue
                if entry.manager.idle() and now - entry.manager.last_activity >= self.settings.session_idle_seconds:
                    entry.state = ManagerState.CLOSING
                    closing.append((key, entry.manager))
        for key, manager in closing:
            try:
                await manager.close()
            finally:
                async with self.lock:
                    entry = self.entries.get(key)
                    if entry is not None and entry.state is ManagerState.CLOSING and entry.manager is manager:
                        self.entries.pop(key, None)

    async def _reap_loop(self):
        while True:
            await asyncio.sleep(min(10, self.settings.session_idle_seconds))
            await self.evict_idle()

    async def close(self):
        if self.reaper:
            self.reaper.cancel()
            await asyncio.gather(self.reaper, return_exceptions=True)
        closing = []
        async with self.lock:
            for key, entry in list(self.entries.items()):
                if entry.state is ManagerState.CREATING:
                    self.entries.pop(key, None)
                    continue
                if entry.manager is not None:
                    entry.state = ManagerState.CLOSING
                    closing.append(entry.manager)
            self.entries.clear()
        await asyncio.gather(*(manager.close() for manager in closing))
