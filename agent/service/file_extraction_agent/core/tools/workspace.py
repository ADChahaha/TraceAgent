"""资源路径 → 受管理目录校验 → 文档工具上下文；索引读取委托 embedding.py。

open_workspace 创建文件访问器和本轮 embedding 访问器；validate_resource 额外校验
索引以保留 HTTP 422 预检。启动通知不遍历目录或返回文档树。
非法目录、外部链接、损坏资源均以 ValueError 结束，不生成任何文件或向量。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from service.file_extraction_agent.core.tools.embedding import EmbeddingResources
from service.file_extraction_agent.core.tools.base import order_key


@dataclass
class FileEntry:
    name: str
    path: str
    kind: str
    order: int


@dataclass
class DocumentFileTree:
    root: Path

    def entries(self, path: str | None = None) -> list[FileEntry]:
        """校验目录路径 → 按数字前缀枚举一层目录和 Markdown 文件。"""

        directory = self._resolve_directory(path)
        entries: list[FileEntry] = []
        for child in sorted(directory.iterdir(), key=lambda p: order_key(p.name)):
            if child.is_dir():
                entries.append(
                    FileEntry(name=child.name, path=str(child), kind="dir", order=order_key(child.name))
                )
            elif child.is_file() and child.suffix == ".md":
                entries.append(
                    FileEntry(name=child.name, path=str(child), kind="md", order=order_key(child.name))
                )
        return sorted(entries, key=lambda entry: entry.order)

    def read(self, path: str) -> str:
        """校验文件属于文档目录 → 以 UTF-8 读取；越界或缺失抛 ValueError。"""

        resolved = self._resolve_file(path)
        return resolved.read_text(encoding="utf-8")

    def scope_path(self, scope: str | None = None) -> Path:
        """空 scope 使用根目录，否则校验目标目录；越界或缺失抛 ValueError。"""

        if scope is None or not str(scope or "").strip():
            return self.root
        candidate = Path(str(scope)).resolve()
        root = self.root.resolve()
        if candidate == root:
            return root
        if root not in candidate.parents:
            raise ValueError("scope escapes the document workspace")
        if not candidate.exists() or not candidate.is_dir():
            raise ValueError(f"scope is not a directory: {scope}")
        return candidate

    def _resolve_directory(self, path: str | None) -> Path:
        if path is None or not str(path or "").strip():
            return self.root
        candidate = Path(str(path)).resolve()
        root = self.root.resolve()
        if candidate == root:
            return root
        if root not in candidate.parents:
            raise ValueError("path escapes the document workspace")
        if not candidate.exists() or not candidate.is_dir():
            raise ValueError(f"path is not a directory: {path}")
        return candidate

    def _resolve_file(self, path: str) -> Path:
        candidate = Path(str(path)).resolve()
        root = self.root.resolve()
        if root not in candidate.parents:
            raise ValueError("file escapes the document workspace")
        if not candidate.exists() or not candidate.is_file():
            raise ValueError(f"file not found: {path}")
        return candidate


@dataclass
class ToolWorkspace:
    document: DocumentFileTree
    embedding: EmbeddingResources


def open_workspace(resource_path: str) -> ToolWorkspace:
    """校验本机资源目录及内部路径 → 创建工具访问上下文。"""
    if not isinstance(resource_path, str) or not resource_path.strip():
        raise ValueError("resource_path is required")
    path = Path(resource_path)
    if not path.is_absolute() or path.is_symlink():
        raise ValueError("resource_path must be a managed absolute path")
    path = path.resolve()
    parent = Path(os.getenv("DOCUMENT_RESOURCES_ROOT", str(Path(__file__).resolve().parents[4] / "data" / "resources"))).resolve()
    if path.parent != parent or not path.name.startswith("res_"):
        raise ValueError("resource_path is outside the managed resource directory")
    try:
        document_root = path / "documents"
        if not document_root.is_dir():
            raise ValueError("missing documents directory")
        for item in path.rglob("*"):
            if item.is_symlink() or not item.resolve().is_relative_to(path):
                raise ValueError("resource contains an external path")
        return ToolWorkspace(DocumentFileTree(document_root), EmbeddingResources(path))
    except OSError as exc:
        raise ValueError(f"invalid document resource: {exc}") from exc


def validate_resource(resource_path: str) -> None:
    """工具侧预检路径、清单、向量和引用；失败在 HTTP 开始前返回。"""
    open_workspace(resource_path).embedding.load_index()
