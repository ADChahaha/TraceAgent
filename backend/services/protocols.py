"""backend 服务层依赖倒置抽象协议（DIP）。

核心会话编排与轮次运行时只依赖本模块声明的抽象接口，不直接导入具体 gRPC 客户端、
SQLite 连接封装或 S3 具体实现；具体适配器统一由 `backend/main.py` 装配注入。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class DatabaseProtocol(Protocol):
    """线程本地 SQLite 连接提供方契约。"""

    def connect(self) -> sqlite3.Connection: ...

    def close(self) -> None: ...


@runtime_checkable
class CompletionStream(Protocol):
    """单轮问答异步事件流契约，支持显式取消。"""

    def cancel(self) -> None: ...

    def __aiter__(self) -> CompletionStream: ...

    async def __anext__(self) -> dict[str, Any]: ...


@runtime_checkable
class AgentGateway(Protocol):
    """问答与会话标题推理网关契约。"""

    def chat_completion(
        self,
        *,
        completion_id: str,
        resource_path: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        run_options: dict[str, Any] | None = None,
    ) -> CompletionStream: ...

    async def generate_title(
        self,
        *,
        question: str,
        filenames: list[str] | None = None,
        timeout_seconds: float = 15.0,
    ) -> str: ...

    async def close(self) -> None: ...


@runtime_checkable
class DocumentGateway(Protocol):
    """文档解析发布与原文块读取网关契约。"""

    async def prepare_resources(
        self,
        *,
        session_id: str,
        files: list[dict[str, Any]],
        remove_raw: Sequence[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]: ...

    async def read_blocks(self, *, bucket: str, keys: list[str]) -> list[dict[str, Any]]: ...

    async def close(self) -> None: ...
