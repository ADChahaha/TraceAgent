"""S3 兼容对象存储路由与 FastAPI 应用。

提供 create_bucket / put_object / get_object / head_object / delete_object /
list_objects_v2 端点，响应遵循 S3 wire 协议（XML 列表、ETag、Content-Length、
XML Error 结构），使 boto3 等标准客户端可直接访问并按错误码分支。底层为本地
目录对象存储，桶名与 key 的合法性由 DirectoryObjectStore 统一校验。
本地开发不做签名鉴权。
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

from fastapi import FastAPI, Request, Response

from storage.core.object_store import DirectoryObjectStore, InvalidBucketName, InvalidKey


def _etag(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _error_response(status_code: int, code: str) -> Response:
    """S3 风格 XML 错误体，客户端按 <Code> 解析错误并分支。"""
    body = ('<?xml version="1.0" encoding="UTF-8"?>'
            f'<Error><Code>{escape(code)}</Code><Message>{escape(code)}</Message></Error>')
    return Response(content=body.encode("utf-8"), status_code=status_code, media_type="application/xml")


def _client_error(exc: ValueError) -> Response:
    code = "InvalidBucketName" if isinstance(exc, InvalidBucketName) else \
        "InvalidKey" if isinstance(exc, InvalidKey) else "InvalidRequest"
    return _error_response(400, code)


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
        payload = await request.body()
        if len(parts) == 1:
            try:
                store.create_bucket(parts[0])
            except ValueError as exc:
                return _client_error(exc)
            return Response(status_code=200, headers={"Location": f"/{parts[0]}"})
        try:
            store.put_object(parts[0], parts[1], payload)
        except ValueError as exc:
            return _client_error(exc)
        return Response(status_code=200, headers={"ETag": f'"{_etag(payload)}"'})

    @app.get("/{bucket:path}")
    def get_or_list(bucket: str, request: Request, list_type: int = 0, prefix: str = "") -> Response:
        parts = bucket.split("/", 1)
        name = parts[0]
        if request.query_params.get("list-type") == "2":
            try:
                keys = store.list_objects(name, prefix or "")
            except ValueError as exc:
                return _client_error(exc)
            return Response(content=_list_xml(name, prefix or "", keys), media_type="application/xml")
        if len(parts) == 1:
            return _error_response(404, "NoSuchKey")
        try:
            data = store.get_object(name, parts[1])
        except ValueError as exc:
            return _client_error(exc)
        if data is None:
            return _error_response(404, "NoSuchKey")
        return Response(
            content=data,
            media_type="application/octet-stream",
            headers={"ETag": f'"{_etag(data)}"', "Content-Length": str(len(data))},
        )

    @app.head("/{bucket:path}")
    def head_object(bucket: str) -> Response:
        parts = bucket.split("/", 1)
        if len(parts) != 2:
            return _error_response(404, "NoSuchKey")
        try:
            info = store.head_object(parts[0], parts[1])
        except ValueError as exc:
            return _client_error(exc)
        if info is None:
            return _error_response(404, "NoSuchKey")
        return Response(status_code=200, headers={"Content-Length": str(info["size"])})

    @app.delete("/{bucket:path}")
    def delete_object(bucket: str) -> Response:
        parts = bucket.split("/", 1)
        if len(parts) != 2:
            return _error_response(400, "InvalidRequest")
        try:
            store.delete_object(parts[0], parts[1])
        except ValueError as exc:
            return _client_error(exc)
        return Response(status_code=204)

    return app


__all__ = ["create_app", "DirectoryObjectStore"]
