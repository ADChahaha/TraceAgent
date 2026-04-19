"""标准化文档输出的共享结果结构。

实现步骤：

```text
文档处理器拿到解析后的内容
  -> 如果某段内容有页面坐标，就先用 BoundingBox 保存 x0/y0/x1/y1
  -> 再把一段文本、页码、bbox、块类型、附加信息组装成 ContentBlock
  -> 一个文档里的全部块、markdown、元信息、warning 再汇总成 ProcessResult
  -> route 层、后续抽取流程、调试代码都只读取这套 dataclass
  -> 不管底层是 PDF 处理器还是 DOCX 处理器，最终都必须产出同一种结果形状
```
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class BoundingBox:
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass(slots=True)
class ContentBlock:
    text: str
    page_no: int | None = None
    bbox: BoundingBox | None = None
    kind: str = "text"
    meta_info: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ProcessResult:
    file_type: str
    filename: str | None = None
    md_list: list[str] = field(default_factory=list)
    markdown: str = ""
    blocks: list[ContentBlock] = field(default_factory=list)
    meta_info: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
