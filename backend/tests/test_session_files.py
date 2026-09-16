"""会话级文件：独立建会话、上传绑定 session、删除重建、轮次复用不替换。"""

import asyncio

import pytest

from backend.services.errors import ValidationError, NotFoundError
from backend.services.session_history import build_snapshot
from backend.tests.test_session_manager import finish, next_type, setup


def file(name, content=b"%PDF-1.4"):
    return {"filename": name, "content": content}


def bundle_paths(rows):
    return [{"type": row["type"], "location": row["location"]}
            for row in rows if row["type"] != "raw"]


def test_create_session_starts_ready_without_turns(tmp_path):
    async def scenario():
        registry, db, agent = await setup(tmp_path)
        try:
            session_id = await registry.create_session()
            assert session_id
            row = db.connect().execute("SELECT * FROM chat_sessions WHERE id=?", (session_id,)).fetchone()
            assert row["status"] == "ready" and row["active_turn_id"] is None
            manager = await registry.get_or_create(session_id)
            context = await manager.create_completion(content="问题", run_options={})
            assert context.turn_id
            call = await agent.created.get()
            await finish(call, manager, context.turn_id)
        finally:
            await registry.close()
            db.close()
    asyncio.run(scenario())


def test_manager_upload_validates_before_document_call(tmp_path):
    async def scenario():
        registry, db, agent = await setup(tmp_path)
        try:
            session_id = await registry.create_session()
            manager = await registry.get_or_create(session_id)
            with pytest.raises(ValidationError):
                await manager.upload_files(files=[])
            with pytest.raises(ValidationError):
                await manager.upload_files(files=[file("bad.txt")])
            with pytest.raises(ValidationError):
                await manager.upload_files(files=[file("a.pdf", b"")])
            # 校验失败不触达 document service。
            assert agent.prepared == []
        finally:
            await registry.close()
            db.close()
    asyncio.run(scenario())


def test_upload_materializes_at_upload_and_binds_to_session(tmp_path):
    async def scenario():
        registry, db, agent = await setup(tmp_path)
        try:
            session_id = await registry.create_session()
            manager = await registry.get_or_create(session_id)
            rows = await manager.upload_files(files=[file("a.pdf", b"aaa"), file("b.docx", b"bbb")])
            # 物化在上传时发生并携带 session_id；轮次执行不再触达准备。
            assert agent.prepared == [(session_id, [file("a.pdf", b"aaa"), file("b.docx", b"bbb")], [])]
            raws = {row["location"]: row["size_bytes"] for row in rows if row["type"] == "raw"}
            assert set(raws) == {f"s3://res_{session_id}/raw/a.pdf", f"s3://res_{session_id}/raw/b.docx"}
            assert set(raws.values()) == {3}
            assert bundle_paths(rows)
            context = await manager.create_completion(content="问题", run_options={})
            snapshot = await build_snapshot(db, context)
            assert snapshot["state"]["resources"] == rows
            call = await agent.created.get()
            assert agent.requests[0]["resource_path"] == bundle_paths(rows)
            await finish(call, manager, context.turn_id)
            assert len(agent.prepared) == 1
        finally:
            await registry.close()
            db.close()
    asyncio.run(scenario())


def test_upload_rejects_bad_type_limits_and_unknown_session(tmp_path):
    async def scenario():
        registry, db, agent = await setup(tmp_path, upload_max_files=2, upload_max_bytes=8)
        try:
            session_id = await registry.create_session()
            manager = await registry.get_or_create(session_id)
            with pytest.raises(ValidationError):
                await manager.upload_files(files=[file("bad.txt")])
            with pytest.raises(NotFoundError):
                await registry.get_or_create("missing")
            await manager.upload_files(files=[file("a.pdf", b"aaa")])
            # 累计文件数：已有 1 个，再传 2 个超过 upload_max_files=2。
            with pytest.raises(ValidationError):
                await manager.upload_files(files=[file("b.pdf"), file("c.pdf")])
            # 累计字节：3 + 8（默认 content）> upload_max_bytes=8。
            with pytest.raises(ValidationError):
                await manager.upload_files(files=[file("b.pdf")])
            with pytest.raises(ValidationError):
                await manager.upload_files(files=[])
        finally:
            await registry.close()
            db.close()
    asyncio.run(scenario())


def test_resources_persist_across_turns_without_replacement(tmp_path):
    async def scenario():
        registry, db, agent = await setup(tmp_path)
        try:
            session_id = await registry.create_session()
            first = await registry.get_or_create(session_id)
            rows = await first.upload_files(files=[file("a.pdf")])
            context = await first.create_completion(content="第一问", run_options={})
            call = await agent.created.get()
            await finish(call, first, context.turn_id)
            second = await registry.get_or_create(session_id)
            context2 = await second.create_completion(content="第二问", run_options={})
            call2 = await agent.created.get()
            # 两次轮次的 resource_path 完全一致；轮次不替换、不准备资源。
            assert agent.requests[1]["resource_path"] == bundle_paths(rows)
            await finish(call2, second, context2.turn_id)
            assert db.connect().execute("SELECT COUNT(*) FROM chat_resources").fetchone()[0] == len(rows)
            assert len(agent.prepared) == 1
        finally:
            await registry.close()
            db.close()
    asyncio.run(scenario())


def test_delete_removes_raw_and_rebuilds_bundle(tmp_path):
    async def scenario():
        registry, db, agent = await setup(tmp_path)
        try:
            session_id = await registry.create_session()
            manager = await registry.get_or_create(session_id)
            rows = await manager.upload_files(files=[file("a.pdf"), file("b.pdf")])
            raw_id = next(row["id"] for row in rows if row["location"].endswith("/raw/a.pdf"))
            context = await manager.create_completion(content="问题", run_options={})
            updated = await manager.remove_file(resource_id=raw_id)
            # 删除调用 agent：files 为空，remove_raw 指向被删文件；bundle 引用整体替换。
            assert agent.prepared[-1] == (session_id, [], [{"type": "raw", "location": f"s3://res_{session_id}/raw/a.pdf"}])
            assert all(not row["location"].endswith("/raw/a.pdf") for row in updated)
            call = await agent.created.get()
            await finish(call, manager, context.turn_id)
            # resource_path 只含 bundle 引用；删除发生在轮次之后，本轮请求不受影响。
            paths = agent.requests[0]["resource_path"]
            assert paths == [{"type": row["type"], "location": row["location"]} for row in updated if row["type"] != "raw"]
            with pytest.raises(NotFoundError):
                await manager.remove_file(resource_id="missing")
            bundle_id = next(row["id"] for row in updated if row["type"] == "documents")
            with pytest.raises(ValidationError):
                await manager.remove_file(resource_id=bundle_id)
        finally:
            await registry.close()
            db.close()
    asyncio.run(scenario())


def test_upload_broadcasts_resources_prepared_to_subscribers(tmp_path):
    async def scenario():
        registry, db, agent = await setup(tmp_path)
        try:
            session_id = await registry.create_session()
            manager = await registry.get_or_create(session_id)
            await manager.upload_files(files=[file("a.pdf")])
            context = await manager.attach()
            rows = await manager.upload_files(files=[file("b.pdf")])
            event = await next_type(context.subscription, "resources.prepared")
            assert event["payload"]["resources"] == bundle_paths(rows)
        finally:
            await registry.close()
            db.close()
    asyncio.run(scenario())
