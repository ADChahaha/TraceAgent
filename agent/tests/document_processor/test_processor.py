from io import BytesIO

import pytest

from document_processor.schemas import ProcessResult
from document_processor.types import FileType, UnsupportedFileTypeError


class NamedBytesIO(BytesIO):
    def __init__(self, data: bytes, filename: str | None) -> None:
        super().__init__(data)
        self.filename = filename


def test_document_processor_base_validates_file_like_input_and_delegates_to_subclass():
    from document_processor.impl.base import BaseDocumentProcessor

    class StubProcessor(BaseDocumentProcessor):
        def __init__(self) -> None:
            self.calls = []

        def _process(self, file_obj):
            self.calls.append(file_obj)
            return ProcessResult(file_type="pdf", filename="sample.pdf")

    processor = StubProcessor()
    file_obj = NamedBytesIO(b"fake", filename="sample.pdf")

    result = processor.process(file_obj)

    assert result.file_type == "pdf"
    assert processor.calls == [file_obj]


def test_document_processor_base_rejects_non_file_like_input():
    from document_processor.impl.base import BaseDocumentProcessor
    from document_processor.processor import InvalidFileObjectError

    class StubProcessor(BaseDocumentProcessor):
        def _process(self, file_obj):
            return ProcessResult(file_type="pdf")

    with pytest.raises(InvalidFileObjectError, match="file-like"):
        StubProcessor().process(object())


def test_process_routes_explicit_file_type_to_registered_processor():
    from document_processor import processor as processor_module
    from document_processor.impl.base import BaseDocumentProcessor
    from document_processor.impl.interface import InternalProcessorInterface

    class PdfStubProcessor(BaseDocumentProcessor):
        def __init__(self) -> None:
            self.calls = []

        def _process(self, file_obj):
            self.calls.append(file_obj)
            return ProcessResult(file_type="pdf", filename="sample.unknown")

    original_types = InternalProcessorInterface._processor_types.copy()
    original_instances = InternalProcessorInterface._processor_instances.copy()
    original_defaults_flag = InternalProcessorInterface._defaults_registered
    try:
        InternalProcessorInterface._processor_types.clear()
        InternalProcessorInterface._processor_instances.clear()
        InternalProcessorInterface._defaults_registered = False
        InternalProcessorInterface.register(FileType.PDF)(PdfStubProcessor)

        result = processor_module.process(
            NamedBytesIO(b"%PDF-1.4", filename="sample.unknown"),
            file_type="pdf",
        )

        assert result.file_type == "pdf"
        assert InternalProcessorInterface._processor_instances[FileType.PDF].calls != []
    finally:
        InternalProcessorInterface._processor_types.clear()
        InternalProcessorInterface._processor_types.update(original_types)
        InternalProcessorInterface._processor_instances.clear()
        InternalProcessorInterface._processor_instances.update(original_instances)
        InternalProcessorInterface._defaults_registered = original_defaults_flag


def test_process_uses_filename_inference_when_file_type_is_omitted():
    from document_processor import processor as processor_module
    from document_processor.impl.base import BaseDocumentProcessor
    from document_processor.impl.interface import InternalProcessorInterface

    class DocxStubProcessor(BaseDocumentProcessor):
        def __init__(self) -> None:
            self.calls = []

        def _process(self, file_obj):
            self.calls.append(file_obj)
            return ProcessResult(file_type="docx", filename="contract.DOCX")

    original_types = InternalProcessorInterface._processor_types.copy()
    original_instances = InternalProcessorInterface._processor_instances.copy()
    original_defaults_flag = InternalProcessorInterface._defaults_registered
    try:
        InternalProcessorInterface._processor_types.clear()
        InternalProcessorInterface._processor_instances.clear()
        InternalProcessorInterface._defaults_registered = False
        InternalProcessorInterface.register(FileType.DOCX)(DocxStubProcessor)

        result = processor_module.process(
            NamedBytesIO(b"fake-docx", filename="contract.DOCX"),
        )

        assert result.file_type == "docx"
        assert InternalProcessorInterface._processor_instances[FileType.DOCX].calls != []
    finally:
        InternalProcessorInterface._processor_types.clear()
        InternalProcessorInterface._processor_types.update(original_types)
        InternalProcessorInterface._processor_instances.clear()
        InternalProcessorInterface._processor_instances.update(original_instances)
        InternalProcessorInterface._defaults_registered = original_defaults_flag


def test_process_rejects_objects_without_file_like_read_method():
    from document_processor import processor as processor_module
    from document_processor.processor import InvalidFileObjectError

    with pytest.raises(InvalidFileObjectError, match="file-like"):
        processor_module.process(object(), file_type="pdf")


def test_process_propagates_unsupported_file_type_errors():
    from document_processor import processor as processor_module

    with pytest.raises(UnsupportedFileTypeError, match="txt"):
        processor_module.process(NamedBytesIO(b"fake", filename="sample.txt"))


def test_register_processor_rejects_non_processor_subclasses():
    from document_processor.impl.interface import InternalProcessorInterface

    with pytest.raises(TypeError, match="BaseDocumentProcessor"):
        @InternalProcessorInterface.register(FileType.PDF)
        class NotAProcessor:
            pass


def test_process_uses_registered_processor_class_when_no_instance_is_injected():
    from document_processor import processor as processor_module
    from document_processor.impl.base import BaseDocumentProcessor
    from document_processor.impl.interface import InternalProcessorInterface

    class RegisteredPdfProcessor(BaseDocumentProcessor):
        def __init__(self) -> None:
            self.calls = []

        def _process(self, file_obj):
            self.calls.append(file_obj)
            return ProcessResult(file_type="pdf", filename="sample.pdf")

    original_types = InternalProcessorInterface._processor_types.copy()
    original_instances = InternalProcessorInterface._processor_instances.copy()
    original_defaults_flag = InternalProcessorInterface._defaults_registered
    try:
        InternalProcessorInterface._processor_types.clear()
        InternalProcessorInterface._processor_instances.clear()
        InternalProcessorInterface._defaults_registered = False
        InternalProcessorInterface.register(FileType.PDF)(RegisteredPdfProcessor)

        result = processor_module.process(
            NamedBytesIO(b"%PDF-1.4", filename="sample.pdf"),
        )

        assert result.file_type == "pdf"
        assert InternalProcessorInterface._processor_instances[FileType.PDF].calls != []
    finally:
        InternalProcessorInterface._processor_types.clear()
        InternalProcessorInterface._processor_types.update(original_types)
        InternalProcessorInterface._processor_instances.clear()
        InternalProcessorInterface._processor_instances.update(original_instances)
        InternalProcessorInterface._defaults_registered = original_defaults_flag
