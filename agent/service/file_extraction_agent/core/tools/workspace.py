"""资源定位数组 → 打开对象存储 → 文档工具上下文；索引读取委托 embedding.py。

load_workspace_payload 在工具子进程里执行：按 type 找到 documents 与 index 位置，
从 storage 服务拉取 documents.zip、加载并校验索引，最后序列化成父进程保存、
每次工具调用原样下发的 workspace payload。
document_tree_from_payload 在只读工具子进程里执行：只用 payload 中的归档 bytes
重建文档树，不再访问对象存储。
非法位置、越界 key、损坏资源均以 ValueError 结束，不生成任何文件或向量。
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from service.object_store import (
    ArchiveObjectStore,
    CompositeObjectStore,
    ObjectStore,
    build_s3_object_store,
    parse_resource_path,
)
from service.file_extraction_agent.core.tools.embedding import (
    EmbeddingResources,
    index_to_payload,
)
from service.file_extraction_agent.core.tools.base import order_key
from service.file_extraction_agent.schemas import ResourceRefs


def _location_by_type(resource_refs: ResourceRefs, resource_type: str) -> str | None:
    """从资源定位数组中按 type 找到对应 location（s3:// URL）。"""
    for ref in resource_refs:
        if ref.type == resource_type and ref.location:
            return ref.location
    return None


class _LocalDirStore:
    """本地目录对象存储（仅测试与本地工具复用，生产走 storage 服务）。"""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def _obj_path(self, bucket: str, key: str) -> Path:
        relative = Path(key)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"key must be a safe relative path: {key}")
        bucket_dir = self.root / bucket
        if not bucket_dir.is_dir():
            raise ValueError(f"bucket does not exist: {bucket}")
        return bucket_dir / relative

    def get_object(self, bucket: str, key: str) -> bytes | None:
        path = self._obj_path(bucket, key)
        if not path.is_file():
            return None
        return path.read_bytes()

    def list_objects(self, bucket: str, prefix: str = "") -> list[str]:
        bucket_dir = self.root / bucket
        if not bucket_dir.is_dir():
            return []
        keys: list[str] = []
        for path in bucket_dir.rglob("*"):
            if not path.is_file():
                continue
            key = path.relative_to(bucket_dir).as_posix()
            if key.startswith(prefix or ""):
                keys.append(key)
        return keys


@dataclass
class FileEntry:
    name: str
    path: str
    kind: str
    order: int


@dataclass
class DocumentFileTree:
    """在 ObjectStore 的 documents 桶内按 key 前缀浏览/读取 .md 文件。"""

    store: ObjectStore
    bucket: str
    root_key: str  # documents 目录在桶内的 key 前缀，如 "documents"

    @classmethod
    def from_local_dir(cls, path: Path) -> "DocumentFileTree":
        """把本地目录当作一个桶构造只读视图，供测试与工具本地复用。"""
        path = Path(path).resolve()
        store = _LocalDirStore(path.parent)
        return cls(store, path.name, "")

    def _full_key(self, key: str) -> str:
        if self.root_key and not key.startswith(self.root_key + "/"):
            raise ValueError(f"path escapes the document workspace: {key}")
        return key

    def entries(self, path: str | None = None) -> list[FileEntry]:
        """校验 key 前缀 → 按数字前缀枚举一层子目录和 Markdown 文件。"""
        prefix = self._scope_prefix(path)
        keys = sorted(self.store.list_objects(self.bucket, prefix=prefix))
        children: dict[str, FileEntry] = {}
        for key in keys:
            if not key.endswith(".md"):
                continue
            relative = key[len(prefix):].lstrip("/")
            if "/" in relative:
                top = relative.split("/", 1)[0]
                child_key = f"{prefix.rstrip('/')}/{top}" if prefix else top
                children.setdefault(
                    child_key,
                    FileEntry(name=top, path=child_key, kind="dir", order=order_key(top)),
                )
            else:
                children.setdefault(
                    key,
                    FileEntry(name=relative, path=key, kind="md", order=order_key(relative)),
                )
        return sorted(children.values(), key=lambda entry: entry.order)

    def read(self, path: str) -> str:
        """校验 key 属于文档目录 → 读取对象内容；越界或缺失抛 ValueError。"""
        key = self._full_key(path)
        data = self.store.get_object(self.bucket, key)
        if data is None:
            raise ValueError(f"file not found: {path}")
        return data.decode("utf-8")

    def scope_path(self, scope: str | None = None) -> str:
        """空 scope 使用文档根 key 前缀；否则校验目标 key 前缀；越界抛 ValueError。"""
        if scope is None or not str(scope or "").strip():
            return self.root_key
        return self._scope_prefix(scope)

    def _scope_prefix(self, path: str | None) -> str:
        if path is None or not str(path or "").strip():
            return self.root_key
        candidate = str(path).lstrip("/")
        root = self.root_key
        if Path(candidate).is_absolute() or ".." in Path(candidate).parts:
            raise ValueError(f"path escapes the document workspace: {path}")
        if root and candidate == root:
            return root
        if root and not candidate.startswith(root + "/"):
            raise ValueError(f"path escapes the document workspace: {path}")
        return candidate.rstrip("/") + "/"


@dataclass
class ToolWorkspace:
    document: DocumentFileTree
    embedding: EmbeddingResources | None = None


def load_workspace_payload(resource_refs: ResourceRefs) -> dict[str, Any]:
    """资源定位 → 拉取归档并加载校验索引 → 父进程保存的 workspace payload。"""
    documents_location = _location_by_type(resource_refs, "documents")
    index_location = _location_by_type(resource_refs, "index")
    if not documents_location or not index_location:
        raise ValueError("resource_path must include documents and index locations")
    doc_bucket, doc_key = parse_resource_path(documents_location)
    idx_bucket, idx_key = parse_resource_path(index_location)
    if doc_bucket != idx_bucket:
        raise ValueError("documents and index must belong to the same resource")
    store = build_s3_object_store()
    archive_bytes = store.get_object(doc_bucket, doc_key)
    if archive_bytes is None:
        raise ValueError(f"missing document archive: {doc_key}")
    archive = ArchiveObjectStore(doc_bucket, archive_bytes)
    composite = CompositeObjectStore(archive, store)
    embedding = EmbeddingResources(composite, idx_bucket, idx_key)
    index = embedding.load_index()
    return {
        "bucket": doc_bucket,
        "documents_archive_b64": base64.b64encode(archive_bytes).decode("ascii"),
        "index": index_to_payload(index),
    }


def document_tree_from_payload(payload: dict[str, Any]) -> DocumentFileTree:
    """workspace payload → 归档内文档树；只读工具子进程不访问 storage 服务。"""
    bucket = str(payload["bucket"])
    archive = ArchiveObjectStore(bucket, base64.b64decode(str(payload["documents_archive_b64"])))
    return DocumentFileTree(archive, bucket, "documents")
