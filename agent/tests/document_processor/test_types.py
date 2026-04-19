from io import BytesIO

import pytest

from document_processor.types import (
    FileType,
    UnsupportedFileTypeError,
    infer_file_type,
)


class NamedBytesIO(BytesIO):
    def __init__(self, data: bytes, filename: str | None) -> None:
        super().__init__(data)
        self.filename = filename


def test_infer_file_type_returns_explicit_supported_type_without_filename_lookup():
    file_obj = NamedBytesIO(b"fake", filename="sample.unknown")

    assert infer_file_type(file_obj, file_type="PDF") is FileType.PDF


def test_infer_file_type_accepts_dot_prefixed_supported_type():
    file_obj = NamedBytesIO(b"fake", filename=None)

    assert infer_file_type(file_obj, file_type=".docx") is FileType.DOCX


def test_infer_file_type_uses_filename_extension_when_type_is_omitted():
    file_obj = NamedBytesIO(b"fake", filename="contract.PdF")

    assert infer_file_type(file_obj) is FileType.PDF


def test_infer_file_type_rejects_unsupported_explicit_type():
    file_obj = NamedBytesIO(b"fake", filename="sample.pdf")

    with pytest.raises(UnsupportedFileTypeError, match="doc"):
        infer_file_type(file_obj, file_type="doc")


def test_infer_file_type_rejects_unknown_filename_extension():
    file_obj = NamedBytesIO(b"fake", filename="sample.txt")

    with pytest.raises(UnsupportedFileTypeError, match="txt"):
        infer_file_type(file_obj)


def test_infer_file_type_requires_recognizable_type_or_filename():
    file_obj = NamedBytesIO(b"fake", filename=None)

    with pytest.raises(
        UnsupportedFileTypeError,
        match="Could not determine file type",
    ):
        infer_file_type(file_obj)
