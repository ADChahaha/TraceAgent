"""`service.document_processor` 的外层编排入口。

实现步骤：

```text
外部调用方传入 file_obj，可选再传 file_type
  -> 这个文件负责外层编排，不直接处理具体文档
  -> 它先检查 file_obj 是否至少有可调用的 read()
  -> 再用显式 file_type 或文件名后缀解析出统一的 FileType
  -> 然后把“已经确定好的 file_type + file_obj”交给 impl/ 里的固定接口类 InternalProcessorInterface
  -> InternalProcessorInterface 在内部只负责注册查找、实例缓存和多态调用
  -> 具体算法类继承 impl/base.py 里的 BaseDocumentProcessor
  -> 外部调用方只需要关心统一入口 process(...)，不需要接触内部注册机制
```
"""

from __future__ import annotations

from service.document_processor.types import FileType, infer_file_type

class InvalidFileObjectError(TypeError):
    """当处理器收到非 file-like 对象时抛出。"""


def process(
    file_obj,
    file_type: str | FileType | None = None,
):
    """把处理请求转交给内部固定入口类完成。"""

    from service.document_processor.impl.interface import InternalProcessorInterface

    validate_file_obj(file_obj)
    resolved_type = infer_file_type(file_obj, file_type=file_type)

    return InternalProcessorInterface.process(
        resolved_type,
        file_obj,
    )


def validate_file_obj(file_obj) -> None:
    """确保外层入口收到的是最小可用的 file-like 对象。"""

    read_method = getattr(file_obj, "read", None)
    if not callable(read_method):
        raise InvalidFileObjectError(
            "Expected a file-like object with a callable read() method."
        )
