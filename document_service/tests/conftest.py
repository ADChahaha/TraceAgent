"""document service 测试的本地 S3-compatible storage 夹具。"""

from __future__ import annotations

import threading
import asyncio
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
import uuid

import pytest
import grpc
from agent_proto import agent_pb2_grpc
from document_service.main import create_server


@pytest.fixture(scope="session", autouse=True)
def storage_server(tmp_path_factory):
    from _pytest.monkeypatch import MonkeyPatch

    import uvicorn
    from storage.main import create_app

    data_root = tmp_path_factory.mktemp("document-storage-data")
    app = create_app(data_root=data_root)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        while not server.started:
            thread.join(timeout=0.05)
            if not thread.is_alive():
                raise RuntimeError("storage server failed to start")
        port = server.servers[0].sockets[0].getsockname()[1]
        with MonkeyPatch.context() as monkeypatch:
            monkeypatch.setenv("S3_ENDPOINT_URL", f"http://127.0.0.1:{port}")
            monkeypatch.setenv("S3_BUCKET_PREFIX", f"test-{uuid.uuid4().hex[:8]}-")
            monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
            monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
            yield
    finally:
        server.should_exit = True
        thread.join(timeout=5)


@pytest.fixture
def s3_store():
    from traceagent_shared.object_store import build_s3_object_store

    return build_s3_object_store()


def resource_bucket(resource_refs) -> str:
    from traceagent_shared.object_store import parse_resource_path

    documents_location = next(ref.location for ref in resource_refs if ref.type == "documents")
    bucket, _ = parse_resource_path(documents_location)
    return bucket


@pytest.fixture
def document_rpc_server_factory():
    @contextmanager
    def running(*, workers=16, **options):
        ready = Future()

        async def serve():
            loop = asyncio.get_running_loop()
            loop.set_default_executor(ThreadPoolExecutor(max_workers=workers))
            stopped = asyncio.Event()
            server = await create_server(**options)
            port = server.add_insecure_port("127.0.0.1:0")
            await server.start()
            ready.set_result((port, loop, stopped))
            try:
                await stopped.wait()
            finally:
                await server.stop(0)

        def run():
            try:
                asyncio.run(serve())
            except BaseException as exc:
                if not ready.done():
                    ready.set_exception(exc)
                else:
                    raise

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        port, loop, stopped = ready.result(timeout=10)
        channel = grpc.insecure_channel(f"127.0.0.1:{port}", options=[
            ("grpc.max_receive_message_length", 64 * 1024 * 1024),
            ("grpc.max_send_message_length", 64 * 1024 * 1024),
        ])
        try:
            grpc.channel_ready_future(channel).result(timeout=5)
            yield channel
        finally:
            channel.close()
            loop.call_soon_threadsafe(stopped.set)
            thread.join(timeout=10)
            assert not thread.is_alive(), "异步 document service 应完成关闭"

    return running


@pytest.fixture
def document_rpc(document_rpc_server_factory):
    with document_rpc_server_factory() as channel:
        yield agent_pb2_grpc.DocumentResourceServiceStub(channel)
