"""纯 OpenVINO 查询编码器：tokenizer + IR → mean pooling → L2 归一化，不依赖 torch。

实现步骤：

```text
OpenVinoQueryEmbedder(model_id)
  -> huggingface_hub 解析本地模型目录
  -> tokenizers.Tokenizer.from_file(tokenizer.json)，设置截断/补齐
  -> openvino.Core().compile_model(openvino/openvino_model.xml, CPU)
  -> 记录 IR 的输入名（input_ids / attention_mask / 可选 token_type_ids）

encode(texts)
  -> tokenizer.encode_batch 得到 input_ids 与 attention_mask
  -> IR 推理得到 last_hidden_state [batch, seq, dim]
  -> 按 attention_mask 做 mean pooling
  -> 每行 L2 归一化，返回 float32 矩阵
```

模型池化配置来自仓库的 1_Pooling/config.json（mean tokens，无 CLS，无 prompt）。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import openvino as ov
from huggingface_hub import snapshot_download
from tokenizers import Tokenizer

DEFAULT_OPENVINO_FILE = "openvino/openvino_model.xml"
DEFAULT_MAX_LENGTH = 512


def _resolve_model_dir(model_id: str) -> Path:
    """优先用本地缓存，缺失时才联网下载。"""
    try:
        return Path(snapshot_download(model_id, local_files_only=True))
    except Exception:
        return Path(snapshot_download(model_id))


class OpenVinoQueryEmbedder:
    """把一个 sentence-transformers 模型的 OpenVINO IR 当作查询编码器使用。"""

    def __init__(
        self,
        model_id: str,
        *,
        file_name: str = DEFAULT_OPENVINO_FILE,
        device: str = "CPU",
        max_length: int = DEFAULT_MAX_LENGTH,
    ) -> None:
        base = _resolve_model_dir(model_id)
        self._tokenizer = Tokenizer.from_file(str(base / "tokenizer.json"))
        self._tokenizer.enable_truncation(max_length=max_length)
        self._tokenizer.enable_padding()
        self._model = ov.Core().compile_model(str(base / file_name), device)
        self._input_names = {port.any_name for port in self._model.inputs}
        self.dimension = 0

    def encode(self, texts: list[str]) -> np.ndarray:
        encodings = self._tokenizer.encode_batch(list(texts))
        input_ids = np.asarray([encoding.ids for encoding in encodings], dtype=np.int64)
        attention_mask = np.asarray(
            [encoding.attention_mask for encoding in encodings], dtype=np.int64
        )

        feeds: dict[str, np.ndarray] = {}
        if "input_ids" in self._input_names:
            feeds["input_ids"] = input_ids
        if "attention_mask" in self._input_names:
            feeds["attention_mask"] = attention_mask
        if "token_type_ids" in self._input_names:
            feeds["token_type_ids"] = np.zeros_like(input_ids)

        hidden = np.asarray(next(iter(self._model(feeds).values())), dtype=np.float32)
        mask = attention_mask[..., None].astype(np.float32)
        pooled = (hidden * mask).sum(axis=1) / np.maximum(mask.sum(axis=1), 1e-9)
        norms = np.linalg.norm(pooled, axis=1, keepdims=True)
        self.dimension = int(pooled.shape[-1])
        return pooled / np.maximum(norms, 1e-12)


__all__ = ["OpenVinoQueryEmbedder", "DEFAULT_OPENVINO_FILE", "DEFAULT_MAX_LENGTH"]
