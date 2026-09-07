"""共享测试夹具：启动 storage 服务供 agent 测试通过 boto3 访问。"""

from __future__ import annotations

import sys
import threading
import uuid
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


@pytest.fixture(scope="session", autouse=True)
def storage_server(tmp_path_factory):
    """启动一个真实的 storage 服务，并把 S3_ENDPOINT_URL 指向它。"""
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
        with MonkeyPatch.context() as mp:
            mp.setenv("S3_ENDPOINT_URL", f"http://127.0.0.1:{port}")
            mp.setenv("S3_BUCKET_PREFIX", f"test-{uuid.uuid4().hex[:8]}-")
            yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)


@pytest.fixture
def s3_store():
    """返回指向测试 storage 服务的 S3ObjectStore。"""
    from service.object_store import build_s3_object_store

    return build_s3_object_store()


def resource_bucket(resource_refs) -> str:
    """从资源定位数组中取 documents 的 bucket。"""
    from service.object_store import parse_resource_path

    documents_location = next(ref.location for ref in resource_refs if ref.type == "documents")
    bucket, _ = parse_resource_path(documents_location)
    return bucket