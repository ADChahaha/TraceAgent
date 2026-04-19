"""把 file-like 输入路由到对应文件类型的处理器。

实现步骤：

```text
调用方传入 file_obj，可选再传 file_type
  -> 先执行 validate_file_obj(file_obj)
  -> 如果对象没有可调用的 read()，立刻抛出 InvalidFileObjectError，不进入后续流程
  -> 通过 infer_file_type(...) 把输入归一化成 FileType.PDF 或 FileType.DOCX
  -> 先去 self.processors 里找这个类型对应的处理器实例
  -> 如果调用方提前注入了处理器，就直接复用这个实例
  -> 如果没有注入，就根据类型映射选择默认实现：
       PDF -> document_processor.impl.pdf.processor.PdfProcessor
       DOCX -> document_processor.impl.doc.processor.DocProcessor
  -> 用 import_module 动态导入对应模块并实例化处理器
  -> 最后调用该处理器的 process(file_obj)
  -> dispatcher 自己不解析文档内容，只负责“校验输入 -> 判断类型 -> 找到正确处理器 -> 把文件交出去”
  -> 输出值就是底层处理器返回的结果对象
```
"""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib import import_module
from typing import Any

from document_processor.types import FileType, infer_file_type


class InvalidFileObjectError(TypeError):
    """当处理器收到非 file-like 对象时抛出。"""


@dataclass(slots=True)
class ProcessorDispatcher:
    """把文件对象分发给负责该标准化类型的处理器。"""

    processors: dict[FileType, Any] = field(default_factory=dict)

    def process(self, file_obj, file_type: str | FileType | None = None):
        validate_file_obj(file_obj)
        resolved_type = infer_file_type(file_obj, file_type=file_type)
        processor = self._resolve_processor(resolved_type)
        return processor.process(file_obj)

    def _resolve_processor(self, file_type: FileType):
        processor = self.processors.get(file_type)
        if processor is not None:
            return processor

        processor = _load_default_processor(file_type)
        self.processors[file_type] = processor
        return processor


def _load_default_processor(file_type: FileType):
    module_name, class_name = _default_processor_spec(file_type)
    try:
        module = import_module(module_name)
        processor_cls = getattr(module, class_name)
    except (ImportError, AttributeError) as exc:
        raise NotImplementedError(
            f"No processor implementation is available for file type {file_type.value!r}."
        ) from exc
    return processor_cls()


def _default_processor_spec(file_type: FileType) -> tuple[str, str]:
    if file_type is FileType.PDF:
        return "document_processor.impl.pdf.processor", "PdfProcessor"
    if file_type is FileType.DOCX:
        return "document_processor.impl.doc.processor", "DocProcessor"

    raise NotImplementedError(
        f"No processor import spec is configured for file type {file_type.value!r}."
    )


def validate_file_obj(file_obj) -> None:
    """确保输入对象提供了这里所需的最小 file-like 接口。"""

    read_method = getattr(file_obj, "read", None)
    if not callable(read_method):
        raise InvalidFileObjectError(
            "Expected a file-like object with a callable read() method."
        )
