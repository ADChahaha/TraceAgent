"""PDF 转 HTML 的对外结果结构。

实现步骤：

```text
processor.process(...) 已经拿到清理后的语义 HTML fragment
  -> 用源文件基名填入 filename
  -> 用语义 HTML fragment 字符串填入 html
  -> 返回 ProcessResult
```
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ProcessResult:
    filename: str
    html: str
    display_html: str | None = None
    markdown: str = ""
    md_list: list[str] = field(default_factory=list)
    blocks: list[dict[str, Any]] = field(default_factory=list)
    semantic_document: dict[str, Any] = field(default_factory=dict)
    meta_info: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
