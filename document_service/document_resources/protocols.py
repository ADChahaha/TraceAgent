"""document_service 依赖倒置抽象协议（DIP）。

核心资源构建、块读取与路由编排只依赖抽象协议与工厂，不直接耦合具体 S3 实现或底层模型加载器。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

from traceagent_shared.object_store import ObjectStore

ObjectStoreFactory = Callable[[], ObjectStore]


@runtime_checkable
class TextEmbedder(Protocol):
    """文档分块向量编码器抽象契约。"""

    def encode(self, texts: list[str]) -> Any: ...


@runtime_checkable
class DocumentParser(Protocol):
    """原始文档解析为统一 HTML 结果的抽象契约。"""

    def process_file(self, uploaded: Any, **kwargs: Any) -> Any: ...
