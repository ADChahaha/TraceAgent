"""会话级文件上传校验、资源物化与只读归档访问辅助。

仅依赖 ObjectStore、DocumentGateway 与 DatabaseProtocol 抽象，不直接构造具体 S3/gRPC 客户端。
"""

from __future__ import annotations

import asyncio
import io
import zipfile
from pathlib import Path
from typing import Any

from traceagent_shared.object_store import ObjectStore, parse_resource_path

from backend.crud import crud
from backend.services.document_view import full_document
from backend.services.errors import BackendServiceError, NotFoundError, ValidationError
from backend.services.protocols import DatabaseProtocol, DocumentGateway


def validate_file_shapes(files: list[dict[str, Any]], supported_file_types: set[str] | tuple[str, ...]) -> None:
    """校验单批上传文件形状、文件名安全性、重名与扩展名白名单。"""
    filenames: set[str] = set()
    for file in files:
        filename = file.get("filename") if isinstance(file, dict) else None
        content = file.get("content") if isinstance(file, dict) else None
        if not isinstance(filename, str) or not filename.strip() or "/" in filename or "\\" in filename:
            raise ValidationError("文件名不能为空且不能包含路径分隔符")
        if filename in filenames:
            raise ValidationError("同一批上传文件名重复")
        filenames.add(filename)
        if Path(filename).suffix.lower().lstrip(".") not in supported_file_types:
            raise ValidationError("只支持 PDF/DOCX 文件")
        if not isinstance(content, bytes) or not content:
            raise ValidationError("文件内容不能为空")


def check_upload_quota(resources: list[dict[str, Any]], files: list[dict[str, Any]], *, max_files: int, max_bytes: int) -> None:
    """基于当前会话已存 raw 资源校验文件数量与字节配额。"""
    raw_rows = [row for row in resources if row["type"] == "raw"]
    if len(raw_rows) + len(files) > max_files:
        raise ValidationError("会话文件数超过限制")
    total = sum(row["size_bytes"] for row in raw_rows) + sum(len(file["content"]) for file in files)
    if total > max_bytes:
        raise ValidationError("会话资源总量超过限制")


def map_raw_sizes(refs: list[dict[str, Any]], files: list[dict[str, Any]]) -> dict[str, int]:
    """把上传文件大小按 raw/<filename> 后缀对齐到 document_service 返回的 raw 引用。"""
    sizes: dict[str, int] = {}
    for file in files:
        for ref in refs:
            if ref["type"] == "raw" and ref["location"].endswith(f"/raw/{file['filename']}"):
                sizes[ref["location"]] = len(file["content"])
    return sizes


def require_documents_location(resources: list[dict[str, Any]]) -> str:
    documents = next((row for row in resources if row["type"] == "documents"), None)
    if documents is None:
        raise NotFoundError("会话没有文档归档")
    return documents["location"]


def _require_store(object_store: ObjectStore | None) -> ObjectStore:
    if object_store is None:
        raise BackendServiceError("对象存储未配置")
    return object_store


async def read_session_block(
    *,
    resources: list[dict[str, Any]],
    document_client: DocumentGateway,
    key: str,
) -> dict[str, Any]:
    """读取会话文档归档内段落原文；bucket 取自本会话的 documents 引用。"""
    location = require_documents_location(resources)
    bucket = location.removeprefix("s3://").partition("/")[0]
    blocks = await document_client.read_blocks(bucket=bucket, keys=[key])
    if not blocks or not blocks[0]["found"]:
        raise NotFoundError("段落不存在")
    return blocks[0]


async def read_session_document(
    *,
    resources: list[dict[str, Any]],
    document_client: DocumentGateway,
    key: str,
) -> dict[str, Any]:
    """读取会话归档内单个 md 文件全文。"""
    bucket = parse_resource_path(require_documents_location(resources))[0]
    blocks = await document_client.read_blocks(bucket=bucket, keys=[key])
    if not blocks or not blocks[0]["found"]:
        raise NotFoundError("文档不存在")
    return {"key": key, "text": blocks[0]["text"]}


async def download_session_file(
    *,
    database: DatabaseProtocol,
    session_id: str,
    resource_id: str,
    object_store: ObjectStore | None,
) -> tuple[dict[str, Any], bytes]:
    """读取会话原始文件字节，校验资源归属会话与类型。"""
    row = crud.get_resource(database.connect(), resource_id)
    if row is None or row["session_id"] != session_id:
        raise NotFoundError("资源不存在")
    if row["type"] != "raw":
        raise ValidationError("只能下载原始文件")
    bucket, key = parse_resource_path(row["location"])
    store = _require_store(object_store)
    data = await asyncio.to_thread(lambda: store.get_object(bucket, key))
    if data is None:
        raise NotFoundError("文件不存在")
    return row, data


async def list_session_documents(
    *,
    resources: list[dict[str, Any]],
    object_store: ObjectStore | None,
) -> list[dict[str, Any]]:
    """列出会话归档内的处理后 md 文件（key 与大小）。"""
    bucket, archive_key = parse_resource_path(require_documents_location(resources))
    store = _require_store(object_store)
    archive = await asyncio.to_thread(lambda: store.get_object(bucket, archive_key))
    if archive is None:
        raise NotFoundError("会话没有文档归档")
    with zipfile.ZipFile(io.BytesIO(archive)) as members:
        return [{"key": info.filename, "size": info.file_size} for info in members.infolist() if not info.is_dir()]


async def read_session_full_document(
    *,
    resources: list[dict[str, Any]],
    object_store: ObjectStore | None,
    key: str,
) -> dict[str, Any]:
    """按当前会话的归档引用读取整份文档，保留各块 key 供前端定位。"""
    bucket, archive_key = parse_resource_path(require_documents_location(resources))
    store = _require_store(object_store)
    archive = await asyncio.to_thread(lambda: store.get_object(bucket, archive_key))
    if archive is None:
        raise NotFoundError("会话没有文档归档")
    return await asyncio.to_thread(full_document, archive, key)
