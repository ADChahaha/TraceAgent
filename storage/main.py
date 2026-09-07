"""S3 兼容对象存储路由与 FastAPI 应用。

提供 create_bucket / put_object / get_object / head_object / delete_object /
list_objects_v2 端点，响应遵循 S3 wire 协议（XML 列表、ETag、Content-Length），
使 boto3 等标准客户端可直接访问。底层为本地目录对象存储。本地开发不做签名鉴权。
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

from fastapi import FastAPI, Request, Response
from fastapi.responses import PlainTextResponse

from storage.core.object_store import DirectoryObjectStore


def _safe_bucket(bucket: str) -> str:
    if not bucket or "/" in bucket or "\\" in bucket:
        raise ValueError("invalid bucket")
    return bucket


def _etag(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _list_xml(bucket: str, prefix: str, keys: list[str]) -> bytes:
    contents = "".join(
        "<Contents>"
        f"<Key>{escape(key)}</Key>"
        f"<LastModified>{_iso(0)}</LastModified>"
        "<ETag></ETag>"
        f"<Size>{0}</Size>"
        "<StorageClass>STANDARD</StorageClass>"
        "</Contents>"
        for key in keys
    )
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
        f"<Name>{escape(bucket)}</Name>"
        f"<Prefix>{escape(prefix)}</Prefix>"
        f"<KeyCount>{len(keys)}</KeyCount>"
        "<MaxKeys>1000</MaxKeys>"
        "<IsTruncated>false</IsTruncated>"
        f"{contents}"
        "</ListBucketResult>"
    )
    return body.encode("utf-8")


def create_app(data_root: str | Path | None = None) -> FastAPI:
    root = Path(data_root or os.getenv("STORAGE_DATA_ROOT", str(Path(__file__).resolve().parent / "data"))).resolve()
    root.mkdir(parents=True, exist_ok=True)
    store = DirectoryObjectStore(root)
    app = FastAPI(title="storage", version="0.1.0")

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    @app.put("/{bucket:path}")
    async def create_or_put(bucket: str, request: Request) -> Response:
        parts = bucket.split("/", 1)
        name = parts[0]
        try:
            _safe_bucket(name)
        except ValueError:
            return PlainTextResponse("InvalidBucketName", status_code=400)
        if len(parts) == 1:
            store.create_bucket(name)
            return Response(status_code=200, headers={"Location": f"/{name}"})
        key = parts[1]
        payload = await request.body()
        try:
            store.put_object(name, key, payload)
        except ValueError:
            return PlainTextResponse("InvalidKey", status_code=400)
        return Response(status_code=200, headers={"ETag": f'"{_etag(payload)}"'})

    @app.get("/{bucket:path}")
    def get_or_list(bucket: str, request: Request, list_type: int = 0, prefix: str = "") -> Response:
        parts = bucket.split("/", 1)
        name = parts[0]
        if request.query_params.get("list-type") == "2":
            try:
                keys = store.list_objects(name, prefix or "")
            except ValueError:
                return PlainTextResponse("InvalidBucketName", status_code=400)
            return Response(
                content=_list_xml(name, prefix or "", keys),
                media_type="application/xml",
            )
        try:
            _safe_bucket(name)
        except ValueError:
            return PlainTextResponse("InvalidBucketName", status_code=400)
        if len(parts) == 1:
            return PlainTextResponse("NoSuchKey", status_code=404)
        key = parts[1]
        data = store.get_object(name, key)
        if data is None:
            return PlainTextResponse("NoSuchKey", status_code=404)
        return Response(
            content=data,
            media_type="application/octet-stream",
            headers={"ETag": f'"{_etag(data)}"', "Content-Length": str(len(data))},
        )

    @app.head("/{bucket:path}")
    def head_object(bucket: str) -> Response:
        parts = bucket.split("/", 1)
        if len(parts) != 2:
            return PlainTextResponse("NoSuchKey", status_code=404)
        try:
            info = store.head_object(parts[0], parts[1])
        except ValueError:
            return PlainTextResponse("InvalidBucketName", status_code=400)
        if info is None:
            return PlainTextResponse("NoSuchKey", status_code=404)
        return Response(status_code=200, headers={"Content-Length": str(info["size"])})

    @app.delete("/{bucket:path}")
    def delete_object(bucket: str) -> Response:
        parts = bucket.split("/", 1)
        if len(parts) != 2:
            return PlainTextResponse("InvalidRequest", status_code=400)
        try:
            store.delete_object(parts[0], parts[1])
        except ValueError:
            return PlainTextResponse("InvalidBucketName", status_code=400)
        return Response(status_code=204)

    return app


__all__ = ["create_app", "DirectoryObjectStore"]