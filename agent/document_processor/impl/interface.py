"""`document_processor` 在 `impl/` 内部固定使用的处理接口类。

实现步骤：

```text
最外层 processor.py 先完成输入校验和 file_type 推断
  -> 然后调用 InternalProcessorInterface.process(file_type, file_obj, ...)
  -> 固定接口类不再负责 file_obj 校验，也不再负责 file_type 推断
  -> 接口类读取自己维护的注册表
  -> 如果默认处理器还没注册，就在类内部补注册一次
  -> 找到对应处理器类后实例化并缓存
  -> 调用具体处理器的 process(file_obj)
  -> 返回具体处理器生成的 ProcessResult
```
"""

from __future__ import annotations

from typing import Callable

from document_processor.impl.base import BaseDocumentProcessor
from document_processor.schemas import ProcessResult
from document_processor.types import FileType


class InternalProcessorInterface:
    """`impl/` 内部固定使用的注册式处理接口。"""

    _processor_types: dict[FileType, type[BaseDocumentProcessor]] = {}
    _processor_instances: dict[FileType, BaseDocumentProcessor] = {}
    _defaults_registered = False

    @classmethod
    def register(
        cls,
        file_type: FileType,
        *,
        replace: bool = True,
    ) -> Callable[[type[BaseDocumentProcessor]], type[BaseDocumentProcessor]]:
        """把具体处理器类注册到当前接口类维护的表里。"""

        def decorator(
            processor_cls: type[BaseDocumentProcessor],
        ) -> type[BaseDocumentProcessor]:
            if not issubclass(processor_cls, BaseDocumentProcessor):
                raise TypeError(
                    "Registered processor must inherit from BaseDocumentProcessor."
                )
            if not replace and file_type in cls._processor_types:
                return processor_cls
            cls._processor_types[file_type] = processor_cls
            cls._processor_instances.pop(file_type, None)
            return processor_cls

        return decorator

    @classmethod
    def process(
        cls,
        file_type: FileType,
        file_obj,
    ):
        processor = cls._resolve_processor(file_type)
        return processor.process(file_obj)

    @classmethod
    def _resolve_processor(
        cls,
        file_type: FileType,
    ) -> BaseDocumentProcessor:
        cls._ensure_default_processors_registered()

        processor = cls._processor_instances.get(file_type)
        if processor is not None:
            return processor

        processor_cls = cls._processor_types.get(file_type)
        if processor_cls is None:
            raise NotImplementedError(
                f"No processor implementation is registered for file type {file_type.value!r}."
            )

        processor = processor_cls()
        cls._processor_instances[file_type] = processor
        return processor

    @classmethod
    def _ensure_default_processors_registered(cls) -> None:
        if cls._defaults_registered:
            return

        class _PlaceholderStructuredProcessor(BaseDocumentProcessor):
            file_type: FileType

            def _process(self, file_obj):
                filename = getattr(file_obj, "filename", None) or getattr(
                    file_obj, "name", None
                )
                return ProcessResult(
                    file_type=self.file_type.value,
                    filename=filename,
                    warnings=[
                        f"{self.file_type.value} processor is registered, but the concrete parsing backend is not implemented yet."
                    ],
                )

        @cls.register(FileType.PDF, replace=False)
        class PdfProcessor(_PlaceholderStructuredProcessor):
            file_type = FileType.PDF

        from document_processor.impl.docx.processor import DocxProcessor

        cls.register(FileType.DOCX, replace=False)(DocxProcessor)

        cls._defaults_registered = True
