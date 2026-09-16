"""storage 服务：S3 兼容 API 的集成测试（用 boto3 作为真实客户端）。"""

from __future__ import annotations

import threading
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from types import SimpleNamespace

import boto3
import pytest
import uvicorn

from storage.main import create_app


def http(method: str, url: str, data: bytes | None = None) -> urllib.request.Response:
    """绕过代理直连测试服务，返回响应对象（4xx/5xx 抛 HTTPError）。"""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(url, data=data, method=method)
    return opener.open(request, timeout=5)


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
        yield SimpleNamespace(client=client, endpoint=endpoint)
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_put_and_get_object_roundtrip(s3):
    bucket = f"b-{uuid.uuid4().hex[:8]}"
    s3.client.create_bucket(Bucket=bucket)
    s3.client.put_object(Bucket=bucket, Key="docs/a.txt", Body=b"hello")
    data = s3.client.get_object(Bucket=bucket, Key="docs/a.txt")["Body"].read()
    assert data == b"hello"


def test_head_object_returns_metadata(s3):
    bucket = f"b-{uuid.uuid4().hex[:8]}"
    s3.client.create_bucket(Bucket=bucket)
    s3.client.put_object(Bucket=bucket, Key="a.md", Body=b"12345")
    response = s3.client.head_object(Bucket=bucket, Key="a.md")
    assert response["ContentLength"] == 5


def test_head_missing_raises(s3):
    bucket = f"b-{uuid.uuid4().hex[:8]}"
    s3.client.create_bucket(Bucket=bucket)
    with pytest.raises(Exception):
        s3.client.head_object(Bucket=bucket, Key="missing.md")


def test_get_missing_raises_no_such_key(s3):
    """缺失对象必须抛 NoSuchKey（S3 XML 错误码可被 botocore 解析），而不是通用 404。"""
    bucket = f"b-{uuid.uuid4().hex[:8]}"
    s3.client.create_bucket(Bucket=bucket)
    with pytest.raises(s3.client.exceptions.NoSuchKey):
        s3.client.get_object(Bucket=bucket, Key="missing.md")


def test_missing_object_error_body_is_s3_xml(s3):
    """错误响应是 S3 XML 结构，Code 为 NoSuchKey。"""
    bucket = f"b-{uuid.uuid4().hex[:8]}"
    s3.client.create_bucket(Bucket=bucket)
    with pytest.raises(urllib.error.HTTPError) as error:
        http("GET", f"{s3.endpoint}/{bucket}/missing.md")
    assert error.value.code == 404
    body = error.value.read()
    assert b"<Code>NoSuchKey</Code>" in body


def test_delete_object(s3):
    bucket = f"b-{uuid.uuid4().hex[:8]}"
    s3.client.create_bucket(Bucket=bucket)
    s3.client.put_object(Bucket=bucket, Key="a.md", Body=b"data")
    s3.client.delete_object(Bucket=bucket, Key="a.md")
    with pytest.raises(Exception):
        s3.client.get_object(Bucket=bucket, Key="a.md")


def test_list_objects_v2_with_prefix(s3):
    bucket = f"b-{uuid.uuid4().hex[:8]}"
    s3.client.create_bucket(Bucket=bucket)
    s3.client.put_object(Bucket=bucket, Key="docs/01/a.md", Body=b"a")
    s3.client.put_object(Bucket=bucket, Key="docs/02/b.md", Body=b"b")
    s3.client.put_object(Bucket=bucket, Key="index/index.json", Body=b"{}")
    response = s3.client.list_objects_v2(Bucket=bucket, Prefix="docs/")
    keys = [item["Key"] for item in response.get("Contents", [])]
    assert set(keys) == {"docs/01/a.md", "docs/02/b.md"}


def test_data_lands_under_data_root(s3, tmp_path):
    bucket = f"b-{uuid.uuid4().hex[:8]}"
    s3.client.create_bucket(Bucket=bucket)
    s3.client.put_object(Bucket=bucket, Key="x.md", Body=b"persist")
    assert (tmp_path / bucket / "x.md").read_bytes() == b"persist"


def test_dot_bucket_rejected_across_operations(s3):
    """桶名 "." 在建桶、读、写、列、删上都被拒绝，不解析到数据根。"""
    bucket = f"b-{uuid.uuid4().hex[:8]}"
    s3.client.create_bucket(Bucket=bucket)
    s3.client.put_object(Bucket=bucket, Key="secret.txt", Body=b"secret")
    with pytest.raises(urllib.error.HTTPError) as error:
        http("GET", f"{s3.endpoint}/./{bucket}/secret.txt")
    assert error.value.code == 400
    assert b"InvalidBucketName" in error.value.read()
    with pytest.raises(urllib.error.HTTPError) as error:
        http("PUT", f"{s3.endpoint}/./{bucket}/injected.txt", data=b"pwn")
    assert error.value.code == 400
    with pytest.raises(urllib.error.HTTPError) as error:
        http("PUT", f"{s3.endpoint}/.")
    assert error.value.code == 400
    with pytest.raises(urllib.error.HTTPError) as error:
        http("GET", f"{s3.endpoint}/.?list-type=2")
    assert error.value.code == 400
    with pytest.raises(urllib.error.HTTPError) as error:
        http("DELETE", f"{s3.endpoint}/./{bucket}/secret.txt")
    assert error.value.code == 400
    assert s3.client.get_object(Bucket=bucket, Key="secret.txt")["Body"].read() == b"secret"


def test_dot_bucket_list_does_not_enumerate_other_buckets(s3):
    """以 "." 列举不得返回任何其他桶的对象。"""
    bucket = f"b-{uuid.uuid4().hex[:8]}"
    s3.client.create_bucket(Bucket=bucket)
    s3.client.put_object(Bucket=bucket, Key="docs/a.txt", Body=b"a")
    with pytest.raises(urllib.error.HTTPError) as error:
        http("GET", f"{s3.endpoint}/./{bucket}?list-type=2")
    assert error.value.code == 400
