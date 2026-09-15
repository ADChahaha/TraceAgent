"""shared object store 测试使用的本地 S3-compatible storage 夹具。"""

from __future__ import annotations

import threading
import uuid

import pytest


@pytest.fixture(scope="session", autouse=True)
def storage_server(tmp_path_factory):
    from _pytest.monkeypatch import MonkeyPatch

    import uvicorn
    from storage.main import create_app

    data_root = tmp_path_factory.mktemp("storage-data")
    app = create_app(data_root=data_root)
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error")
    server = uvicorn.Server(config)
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
