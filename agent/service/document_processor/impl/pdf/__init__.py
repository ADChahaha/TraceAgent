"""PDF 处理器包。

实现步骤：

```text
调用方或注册表需要 `PdfProcessor`
  -> Python 先加载 `impl/pdf/__init__.py`
  -> 这个文件从 `processor.py` 导入默认 `PdfProcessor`
  -> 同时从 `paddle_processor.py` 导入可选 `PdfPaddleProcessor`
  -> 同时从 `marker_processor.py` 导入可选 `PdfMarkerProcessor`
  -> 不在这里处理 PDF，也不在这里做注册逻辑
  -> 统一把 PDF 处理器类暴露给包外使用
```
"""

from service.document_processor.impl.pdf.marker_processor import PdfMarkerProcessor
from service.document_processor.impl.pdf.paddle_processor import PdfPaddleProcessor
from service.document_processor.impl.pdf.processor import PdfProcessor

__all__ = ["PdfMarkerProcessor", "PdfPaddleProcessor", "PdfProcessor"]
