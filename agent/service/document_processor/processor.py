"""PDF 文件对象到 MinerU HTML 的 pipeline 入口。

实现步骤：

```text
调用方传入 file_obj，可选传 file_type
  -> validate_file_obj(file_obj) 检查 read() 是否可调用
  -> resolve_filename(file_obj) 从 filename/name 取源文件基名，没有则用 document.pdf
  -> validate_pdf_type(file_type, filename) 确认显式类型或文件后缀是 PDF
  -> read_source_bytes(file_obj) 读取 PDF 二进制并尽量复位文件指针
  -> convert_pdf_bytes_to_content_list(source_bytes, filename) 调用 MinerU pipeline
  -> build_html_from_content_list(content_list) 生成抽取友好的 traceable HTML
  -> build_display_html_from_content_list(content_list) 生成用户展示 HTML
  -> ProcessResult(filename, html)
```
"""

from __future__ import annotations

from pathlib import Path

from service.document_processor.mineru_converter import (
    convert_pdf_bytes_to_content_list,
)
from service.document_processor.mineru_html import (
    build_blocks_from_content_list,
    build_display_html_from_content_list,
    build_html_from_content_list,
    build_markdown_from_content_list,
    build_semantic_document_from_content_list,
)
from service.document_processor.schemas import ProcessResult


class InvalidFileObjectError(TypeError):
    """当处理器收到非 file-like 对象时抛出。"""


class UnsupportedFileTypeError(ValueError):
    """当输入不是 PDF，或无法确认是 PDF 时抛出。"""


def process(file_obj, file_type: str | None = None) -> ProcessResult:
    """把一个 PDF 文件对象转换成抽取友好的 HTML。"""

    validate_file_obj(file_obj)
    filename = resolve_filename(file_obj)
    validate_pdf_type(file_type=file_type, filename=filename)
    source_bytes = read_source_bytes(file_obj)
    content_list = convert_pdf_bytes_to_content_list(source_bytes, filename)
    blocks = build_blocks_from_content_list(content_list)
    return ProcessResult(
        filename=filename,
        html=build_html_from_content_list(content_list),
        display_html=build_display_html_from_content_list(content_list),
        markdown=build_markdown_from_content_list(content_list),
        md_list=[block["text"] for block in blocks if block.get("text")],
        blocks=blocks,
        semantic_document=build_semantic_document_from_content_list(content_list),
        meta_info={"engine": "mineru-pipeline"},
        warnings=[],
    )


def validate_file_obj(file_obj) -> None:
    """确保入口收到的是最小可用的 file-like 对象。"""

    read_method = getattr(file_obj, "read", None)
    if not callable(read_method):
        raise InvalidFileObjectError(
            "Expected a file-like object with a callable read() method."
        )


def resolve_filename(file_obj) -> str:
    """从上传对象里取源文件名，缺省时回退为 document.pdf。"""

    for attr_name in ("filename", "name"):
        value = getattr(file_obj, attr_name, None)
        if isinstance(value, str) and value.strip():
            return Path(value).name
    return "document.pdf"


def validate_pdf_type(*, file_type: str | None, filename: str) -> None:
    """确认显式文件类型或文件名后缀只指向 PDF。"""

    if file_type is not None:
        normalized = normalize_file_type(file_type)
        if normalized != "pdf":
            raise UnsupportedFileTypeError(f"Unsupported file type: {file_type!r}.")
        return

    suffix = Path(filename).suffix
    if not suffix:
        raise UnsupportedFileTypeError(
            f"Could not determine PDF file type from filename: {filename!r}."
        )
    normalized = normalize_file_type(suffix)
    if normalized != "pdf":
        raise UnsupportedFileTypeError(f"Unsupported file type: {suffix!r}.")


def normalize_file_type(value: str) -> str:
    """把用户传入的文件类型或后缀归一化成小写无点字符串。"""

    return str(value).strip().lower().lstrip(".")


def read_source_bytes(file_obj) -> bytes:
    """读取 PDF 二进制内容，并在支持 seek() 时把指针复位到开头。"""

    if hasattr(file_obj, "seek"):
        file_obj.seek(0)
    source_bytes = file_obj.read()
    if hasattr(file_obj, "seek"):
        file_obj.seek(0)
    return source_bytes
