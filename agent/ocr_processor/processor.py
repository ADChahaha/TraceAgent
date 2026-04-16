from ocr_processor.impl.base import InvalidFileObjectError, Processor
from ocr_processor.impl.dispatcher import ProcessorDispatcher
from ocr_processor.impl.doc import DocProcessor
from ocr_processor.impl.pdf import PdfProcessor
from ocr_processor.schemas import BoundingBox, ContentBlock, ProcessResult
from ocr_processor.types import FileType, UnsupportedFileTypeError, infer_file_type

_dispatcher = ProcessorDispatcher()


def process(file_obj, file_type: str | FileType | None = None) -> ProcessResult:
    """
    Public convenience entrypoint.

    Typical usage:
        from ocr_processor.processor import process
        result = process(file_obj)
    """

    return _dispatcher.process(file_obj=file_obj, file_type=file_type)

__all__ = [
    "BoundingBox",
    "ContentBlock",
    "DocProcessor",
    "FileType",
    "InvalidFileObjectError",
    "PdfProcessor",
    "ProcessResult",
    "Processor",
    "ProcessorDispatcher",
    "UnsupportedFileTypeError",
    "infer_file_type",
    "process",
]
