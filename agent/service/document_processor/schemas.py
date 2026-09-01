"""PDF 转 HTML 的对外结果结构。

实现步骤：

```text
processor.process(...) 已经拿到带 CSS 的完整 HTML 文档
  -> 用源文件基名填入 filename
  -> 用 HTML 文档字符串填入 html
  -> 返回 ProcessResult
```
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ProcessResult:
    filename: str
    html: str
