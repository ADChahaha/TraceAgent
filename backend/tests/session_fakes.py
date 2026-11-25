"""SessionManager / SessionRegistry 测试共用的内存替身与异步辅助函数。"""

from __future__ import annotations

import asyncio
import copy

from backend.core.config import BackendSettings
from backend.core.db import ThreadLocalDatabase, initialize_database
from backend.services.session_registry import SessionRegistry


class FakeCall:
    def __init__(self):
        self.events = asyncio.Queue()
        self.cancelled = False

    def cancel(self):
        self.cancelled = True
        self.events.put_nowait(None)

    def __aiter__(self):
        return self

    async def __anext__(self):
        event = await self.events.get()
        if event is None:
            raise StopAsyncIteration
        return event


class FakeStore:
    """内存对象存储替身，镜像 document service 发布 raw/documents.zip 的真实落点。"""

    def __init__(self):
        self.objects = {}

    def create_bucket(self, bucket):
        self.objects.setdefault(bucket, {})

    def put_object(self, bucket, key, data, content_type=None):
        self.objects.setdefault(bucket, {})[key] = bytes(data)

    def get_object(self, bucket, key):
        return self.objects.get(bucket, {}).get(key)

    def head_object(self, bucket, key):
        data = self.objects.get(bucket, {}).get(key)
        return None if data is None else {"size": len(data)}

    def delete_object(self, bucket, key):
        self.objects.get(bucket, {}).pop(key, None)

    def list_objects(self, bucket, prefix=""):
        return sorted(key for key in self.objects.get(bucket, {}) if key.startswith(prefix))


class FakeAgent:
    def __init__(self, object_store=None):
        self.calls = []
        self.requests = []
        self.created = asyncio.Queue()
        self.prepared = []
        self.block_reads = []
        self.block_texts = {}
        self.object_store = object_store

    async def prepare_resources(self, *, session_id, files, remove_raw=None):
        self.prepared.append((session_id, files, list(remove_raw or [])))
        bucket = f"res_{session_id}"
        if self.object_store is not None:
            self.object_store.create_bucket(bucket)
        refs = [
            {"type": "documents", "location": f"s3://{bucket}/documents.zip"},
            {"type": "index", "location": f"s3://{bucket}/index"},
        ]
        removed = {ref["location"] for ref in (remove_raw or [])}
        for file in files:
            location = f"s3://{bucket}/raw/{file['filename']}"
            if location in removed:
                continue
            refs.append({"type": "raw", "location": location})
            if self.object_store is not None:
                self.object_store.put_object(bucket, f"raw/{file['filename']}", file["content"])
        for ref in remove_raw or []:
            from traceagent_shared.object_store import parse_resource_path
            bucket_name, key = parse_resource_path(ref["location"])
            if self.object_store is not None and ref["type"] == "raw":
                self.object_store.delete_object(bucket_name, key)
        return refs

    async def read_blocks(self, *, bucket, keys):
        self.block_reads.append((bucket, list(keys)))
        if self.object_store is not None:
            import io
            import zipfile
            archive = self.object_store.get_object(bucket, "documents.zip")
            if archive is not None:
                with zipfile.ZipFile(io.BytesIO(archive)) as members:
                    names = set(members.namelist())
                    return [
                        {
                            "key": key,
                            "text": members.read(key).decode("utf-8") if key in names else "",
                            "found": key in names,
                        }
                        for key in keys
                    ]
        return [{"key": key, "text": self.block_texts.get(key, ""), "found": key in self.block_texts} for key in keys]

    def chat_completion(self, **request):
        call = FakeCall()
        self.requests.append(copy.deepcopy(request))
        self.calls.append(call)
        self.created.put_nowait(call)
        return call


async def setup(tmp_path, **overrides):
    settings = BackendSettings(database_path=tmp_path / "sessions.sqlite3", **overrides)
    database = ThreadLocalDatabase(settings.database_path)
    initialize_database(database.connect())
    agent = FakeAgent(object_store=FakeStore())
    registry = SessionRegistry(
        database=database,
        agent_client=agent,
        settings=settings,
        object_store=agent.object_store,
    )
    await registry.start()
    return registry, database, agent


async def new_session_complete(registry, content, **kwargs):
    """先独立建会话，再在该会话上发起轮次。"""
    session_id = await registry.create_session()
    manager = await registry.get_or_create(session_id)
    context = await manager.create_completion(content=content, **kwargs)
    return manager, context


async def next_type(subscription, expected):
    while True:
        event = await asyncio.wait_for(subscription.receive(), 2)
        if event["type"] == expected:
            return event


async def wait_for_condition(predicate, timeout=2):
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("等待条件超时")
        await asyncio.sleep(0.01)


def expire_idle(manager, registry):
    """按当前单调时钟把会话标为超过空闲阈值，不依赖宿主机开机时长。"""
    manager.last_activity = asyncio.get_running_loop().time() - registry.settings.session_idle_seconds - 1


async def finish(call, manager, turn_id, text="回答"):
    context = await manager.attach()
    await call.events.put({"type": "model_message.done", "seq": 1, "message_id": "m1", "content": text})
    await call.events.put({"type": "completion.completed", "seq": 2})
    await next_type(context.subscription, "turn.completed")
    await manager.detach(context.subscription.id)
