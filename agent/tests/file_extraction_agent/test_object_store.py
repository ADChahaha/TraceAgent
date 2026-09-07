"""ObjectStore 通用 S3 语义接口与 boto3 实现、s3:// URL 解析的测试。"""

from __future__ import annotations

import pytest

from service.object_store import ObjectStore, S3ObjectStore, build_s3_object_store, parse_resource_path


def test_parse_resource_path_root():
    bucket, key = parse_resource_path("s3://res_abc")
    assert bucket == "res_abc"
    assert key == ""


def test_parse_resource_path_with_key():
    bucket, key = parse_resource_path("s3://res_abc/documents/01/a.md")
    assert bucket == "res_abc"
    assert key == "documents/01/a.md"


def test_parse_resource_path_rejects_non_s3():
    with pytest.raises(ValueError):
        parse_resource_path("/local/path")


def test_s3_object_store_interface_shape():
    assert callable(S3ObjectStore.create_bucket)
    assert callable(S3ObjectStore.put_object)
    assert callable(S3ObjectStore.get_object)
    assert callable(S3ObjectStore.head_object)
    assert callable(S3ObjectStore.delete_object)
    assert callable(S3ObjectStore.list_objects)


def test_s3_object_store_bucket_prefix(monkeypatch):
    store = S3ObjectStore(endpoint_url="http://localhost:9000", bucket_prefix="tenant-")
    assert store._bucket("res_abc") == "tenant-res_abc"
    assert store._bucket("x") == "tenant-x"


def test_build_s3_object_store_uses_env(monkeypatch):
    monkeypatch.setenv("S3_ENDPOINT_URL", "http://127.0.0.1:9999")
    monkeypatch.setenv("S3_BUCKET_PREFIX", "pre-")
    store = build_s3_object_store()
    assert store._client.meta.endpoint_url == "http://127.0.0.1:9999"
    assert store.bucket_prefix == "pre-"