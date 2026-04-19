"""文档标准化结果结构的统一导出入口。

实现步骤：

```text
调用方执行 from document_processor import ...
  -> Python 先加载这个 __init__.py
  -> 这个文件不会处理 PDF、DOCX，也不会做类型判断
  -> 它只从 schemas.py 导入 BoundingBox、ContentBlock、ProcessResult
  -> 再通过 __all__ 明确把这 3 个名字暴露为包级公共接口
  -> 调用方以后可以直接从 document_processor 导入统一结果结构
```
"""

from document_processor.schemas import BoundingBox, ContentBlock, ProcessResult

__all__ = ["BoundingBox", "ContentBlock", "ProcessResult"]
