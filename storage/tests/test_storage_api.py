"""storage 服务：S3 兼容 API 的集成测试（用 boto3 作为真实客户端）。"""

from __future__ import annotations

import threading
import uuid
from pathlib import Path

import boto3
import pytest
import uvicorn

from storage.main import create_app


@pytest.fixture
def s3(tmp_path):
    app = create_app(data_root=tmp_path)
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        while not server.started:
            thread.join(timeout=0.05)
        port = server.servers[0].sockets[0].getsockname()[1]
        endpoint = f"http://127.0.0.1:{port}"
        client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id="minioadmin",
            aws_secret_access_key="minioadmin",
            region_name="us-east-1",
        )
        yield client
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_put_and_get_object_roundtrip(s3):
    bucket = f"b-{uuid.uuid4().hex[:8]}"
    s3.create_bucket(Bucket=bucket)
    s3.put_object(Bucket=bucket, Key="docs/a.txt", Body=b"hello")
    data = s3.get_object(Bucket=bucket, Key="docs/a.txt")["Body"].read()
    assert data == b"hello"


def test_head_object_returns_metadata(s3):
    bucket = f"b-{uuid.uuid4().hex[:8]}"
    s3.create_bucket(Bucket=bucket)
    s3.put_object(Bucket=bucket, Key="a.md", Body=b"12345")
    response = s3.head_object(Bucket=bucket, Key="a.md")
    assert response["ContentLength"] == 5


def test_head_missing_raises(s3):
    bucket = f"b-{uuid.uuid4().hex[:8]}"
    s3.create_bucket(Bucket=bucket)
    with pytest.raises(Exception):
        s3.head_object(Bucket=bucket, Key="missing.md")


def test_get_missing_raises(s3):
    bucket = f"b-{uuid.uuid4().hex[:8]}"
    s3.create_bucket(Bucket=bucket)
    with pytest.raises(Exception):
        s3.get_object(Bucket=bucket, Key="missing.md")


def test_delete_object(s3):
    bucket = f"b-{uuid.uuid4().hex[:8]}"
    s3.create_bucket(Bucket=bucket)
    s3.put_object(Bucket=bucket, Key="a.md", Body=b"data")
    s3.delete_object(Bucket=bucket, Key="a.md")
    with pytest.raises(Exception):
        s3.get_object(Bucket=bucket, Key="a.md")


def test_list_objects_v2_with_prefix(s3):
    bucket = f"b-{uuid.uuid4().hex[:8]}"
    s3.create_bucket(Bucket=bucket)
    s3.put_object(Bucket=bucket, Key="docs/01/a.md", Body=b"a")
    s3.put_object(Bucket=bucket, Key="docs/02/b.md", Body=b"b")
    s3.put_object(Bucket=bucket, Key="index/index.json", Body=b"{}")
    response = s3.list_objects_v2(Bucket=bucket, Prefix="docs/")
    keys = [item["Key"] for item in response.get("Contents", [])]
    assert set(keys) == {"docs/01/a.md", "docs/02/b.md"}


def test_data_lands_under_data_root(s3, tmp_path):
    bucket = f"b-{uuid.uuid4().hex[:8]}"
    s3.create_bucket(Bucket=bucket)
    s3.put_object(Bucket=bucket, Key="x.md", Body=b"persist")
    assert (tmp_path / bucket / "x.md").read_bytes() == b"persist"