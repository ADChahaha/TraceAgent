"""PDF 处理器包。

实现步骤：

```text
调用方或注册表需要 `PdfProcessor`
  -> Python 先加载 `impl/pdf/__init__.py`
  -> 这个文件只从 `processor.py` 导入 `PdfProcessor`
  -> 不在这里处理 PDF，也不在这里做注册逻辑
  -> 统一把 `PdfProcessor` 暴露给包外使用
```
"""

from service.document_processor.impl.pdf.processor import PdfProcessor

__all__ = ["PdfProcessor"]
