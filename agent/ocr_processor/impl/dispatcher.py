from __future__ import annotations

from importlib import import_module
from typing import Any

from ocr_processor.schemas import ProcessResult
from ocr_processor.types import FileType, UnsupportedFileTypeError, infer_file_type


class ProcessorDispatcher:
    """
    Enum-style dispatcher, similar to matching on a Rust enum variant.

    Example:
        dispatcher.process(file_obj)
        dispatcher.process(file_obj, FileType.PDF)
        dispatcher.process(file_obj, "docx")
    """

    def process(
        self,
        file_obj: Any,
        file_type: str | FileType | None = None,
    ) -> ProcessResult:
        normalized = infer_file_type(file_obj) if file_type is None else FileType.normalize(file_type)
        processor = self._select_processor(normalized)
        return processor.process(file_obj)

    def _select_processor(self, file_type: FileType):
        match file_type:
            case FileType.PDF:
                processor_cls = _import_processor(
                    "ocr_processor.impl.pdf.processor",
                    "PdfProcessor",
                )
                return processor_cls()
            case FileType.DOC | FileType.DOCX:
                processor_cls = _import_processor(
                    "ocr_processor.impl.doc.processor",
                    "DocProcessor",
                )
                return processor_cls()
            case _:
                raise UnsupportedFileTypeError(f"Unsupported file type: {file_type}")


def _import_processor(module_name: str, class_name: str):
    module = import_module(module_name)
    return getattr(module, class_name)
