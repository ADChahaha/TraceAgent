"""文档资源生成阶段的 embedding 模型与 tokenizer 封装。

`model.py` 负责真实 embedding 模型的惰性加载与 `tokenize` 函数构造，供
资源准备使用；查询模型由 Agent 的 tools/embedding.py 管理。设计上
**模块 import 时不加载任何重依赖**：`torch`、`sentence-transformers`、
`openvino` 只在 `get_embedder` 真正被调用时才导入，因此单元测试无需安装
这些包也能 import 本模块。

实现步骤：

```text
get_embedder(model_id, backend)
  -> 检查模块级缓存（按 model_id + backend 维度）
  -> 未命中时按需 import sentence_transformers 并构造 SentenceTransformer
  -> backend 为 openvino 时传 backend="openvino"（需 optimum-intel）
  -> 返回编码器包装，文档向量由 index.build_index 做 L2 归一化后落盘

get_tokenizer(model_id)
  -> 从句子编码器的 tokenizer 构造一个返回带字符 offsets 的 token 序列函数
  -> 该函数的返回形如 [(start, end), ...]，供 index.chunk_text 使用
```

环境配置：

- `EMBEDDING_MODEL`：模型 ID，默认 `hotchpotch/bekko-embedding-v1-a8m`。
- `EMBEDDING_BACKEND`：`openvino`（默认）或 `torch`。
- OpenVINO 后端需要 `sentence-transformers[openvino]`，即 `optimum-intel`。
"""

from __future__ import annotations

import os
from typing import Any, Callable, Sequence

DEFAULT_EMBEDDING_MODEL = "hotchpotch/bekko-embedding-v1-a8m"

_backend_cache: dict[tuple[str, str], Any] = {}


class EmbeddingModel:
    """封装一个句子编码器，暴露统一的 encode() 与 tokenize()。"""

    def __init__(self, model: Any, tokenize: Callable[[str], Sequence[tuple[int, int]]], dim: int) -> None:
        self._model = model
        self.encode = model.encode
        self.tokenize = tokenize
        self.dimension = dim


def get_embedder(
    model_id: str | None = None,
    backend: str | None = None,
) -> EmbeddingModel:
    """Get a lazily-constructed embedding model, cached per (model_id, backend)."""

    model_id = model_id or os.getenv("EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)
    backend = backend or os.getenv("EMBEDDING_BACKEND", "openvino")
    key = (model_id, backend)
    cached = _backend_cache.get(key)
    if cached is not None:
        return cached

    from sentence_transformers import SentenceTransformer

    if backend == "openvino":
        model = SentenceTransformer(model_id, backend="openvino", trust_remote_code=True)
    else:
        model = SentenceTransformer(model_id, trust_remote_code=True)

    tokenize = _model_tokenize(model)
    dim = int(model.get_sentence_embedding_dimension())
    wrapper = EmbeddingModel(model, tokenize, dim)
    _backend_cache[key] = wrapper
    return wrapper


def get_tokenizer(model_id: str | None = None) -> Callable[[str], Sequence[tuple[int, int]]]:
    """Return a tokenization function returning character-offset token spans."""

    model_id = model_id or os.getenv("EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(model_id, trust_remote_code=True)
    return _model_tokenize(model)


def _model_tokenize(model: Any) -> Callable[[str], Sequence[tuple[int, int]]]:
    def tokenize(text: str) -> Sequence[tuple[int, int]]:
        encoded = model.tokenizer(text, return_offsets_mapping=True, return_tensors=None)
        offsets = encoded.get("offset_mapping", [])
        return [(int(start), int(end)) for start, end in offsets if start != end]

    return tokenize


__all__ = ["EmbeddingModel", "get_embedder", "get_tokenizer", "DEFAULT_EMBEDDING_MODEL"]
