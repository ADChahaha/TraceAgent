"""通用对象存储接口（S3 语义）与 boto3 实现。

业务代码只依赖 ObjectStore 接口（bucket + key 语义），不依赖具体实现。当前实现为
S3ObjectStore：通过 boto3 访问 storage 服务（或任何 S3 兼容 endpoint）的 S3 API。

资源定位统一用 s3://<bucket>[/<key>] 形式表达（parse_resource_path），
写侧和读侧都用它解析出 bucket 与 key。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol

import boto3


@dataclass(frozen=True)
class ResourceRef:
    """资源定位项：type（raw/documents/index）+ location（s3:// URL）。"""

    type: str
    location: str


class ObjectStore(Protocol):
    """对象存储的 S3 语义接口。"""

    def create_bucket(self, bucket: str) -> None: ...
    def put_object(self, bucket: str, key: str, data: bytes, content_type: str | None = None) -> None: ...
    def get_object(self, bucket: str, key: str) -> bytes | None: ...
    def head_object(self, bucket: str, key: str) -> dict | None: ...
    def delete_object(self, bucket: str, key: str) -> None: ...
    def list_objects(self, bucket: str, prefix: str = "") -> list[str]: ...


class S3ObjectStore:
    """boto3 实现的 S3 兼容对象存储客户端。"""

    def __init__(self, *, endpoint_url: str | None = None, bucket_prefix: str = "") -> None:
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=os.getenv("S3_ACCESS_KEY", "minioadmin"),
            aws_secret_access_key=os.getenv("S3_SECRET_KEY", "minioadmin"),
            region_name="us-east-1",
        )
        self.bucket_prefix = bucket_prefix

    def _bucket(self, bucket: str) -> str:
        return f"{self.bucket_prefix}{bucket}" if self.bucket_prefix else bucket

    def create_bucket(self, bucket: str) -> None:
        self._client.create_bucket(Bucket=self._bucket(bucket))

    def put_object(self, bucket: str, key: str, data: bytes, content_type: str | None = None) -> None:
        kwargs = {"Bucket": self._bucket(bucket), "Key": key, "Body": data}
        if content_type:
            kwargs["ContentType"] = content_type
        self._client.put_object(**kwargs)

    def get_object(self, bucket: str, key: str) -> bytes | None:
        try:
            response = self._client.get_object(Bucket=self._bucket(bucket), Key=key)
        except self._client.exceptions.NoSuchKey:
            return None
        return response["Body"].read()

    def head_object(self, bucket: str, key: str) -> dict | None:
        try:
            response = self._client.head_object(Bucket=self._bucket(bucket), Key=key)
        except self._client.exceptions.ClientError:
            return None
        return {"size": response.get("ContentLength")}

    def delete_object(self, bucket: str, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket(bucket), Key=key)

    def list_objects(self, bucket: str, prefix: str = "") -> list[str]:
        response = self._client.list_objects_v2(Bucket=self._bucket(bucket), Prefix=prefix)
        return [item["Key"] for item in response.get("Contents", [])]


def build_s3_object_store() -> S3ObjectStore:
    """按环境变量构造默认 S3ObjectStore。

    S3_ENDPOINT_URL：storage 服务地址，默认 http://localhost:9000
    S3_BUCKET_PREFIX：可选桶名前缀。
    """
    return S3ObjectStore(
        endpoint_url=os.getenv("S3_ENDPOINT_URL", "http://localhost:9000"),
        bucket_prefix=os.getenv("S3_BUCKET_PREFIX", ""),
    )


def parse_resource_path(resource_path: str) -> tuple[str, str]:
    """解析 s3://<bucket>[/<key>] -> (bucket, key)。

    bucket 必填；key 可省略，缺省为空串（指向资源根）。非 s3:// 前缀抛 ValueError。
    """
    if not isinstance(resource_path, str) or not resource_path.startswith("s3://"):
        raise ValueError(f"resource_path must be an s3:// URL: {resource_path!r}")
    remainder = resource_path[len("s3://"):]
    if not remainder or remainder.startswith("/"):
        raise ValueError(f"resource_path must include a bucket: {resource_path!r}")
    first_slash = remainder.find("/")
    if first_slash == -1:
        return remainder, ""
    bucket = remainder[:first_slash]
    key = remainder[first_slash + 1:].lstrip("/")
    return bucket, key


__all__ = [
    "ObjectStore",
    "S3ObjectStore",
    "build_s3_object_store",
    "parse_resource_path",
]