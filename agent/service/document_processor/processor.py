"""PDF / DOCX 文件对象到 traceable HTML 的唯一入口。

对外只暴露一个接口：`process(file_obj, file_type=None)`。模块内部只负责
入口校验、类型分流和字节读取，实际的 PDF（MinerU）与 DOCX（python-docx）
解析分别交给 `pdf` / `docx` 子包各自暴露的单一函数。

实现步骤：

```text
调用方传入 file_obj，可选传 file_type（pdf / docx）
  -> validate_file_obj(file_obj)            检查 read() 是否可调用
  -> resolve_filename(file_obj, fallback?)  从 filename/name 取源文件基名
  -> detect_file_type(file_type, filename)  显式类型优先，否则看后缀
       ├─ "pdf"  -> _process_pdf(...)，engine=mineru-pipeline
       └─ "docx" -> _process_docx(...)，engine=python-docx
```

PDF 分支：

```text
file_obj
  -> read_source_bytes(...) 读取 bytes 并复位文件指针
  -> pdf.build_html_from_content_list / convert_pdf_to_html(...) 生成完整 HTML
  -> ProcessResult(filename, html)
```

换成包级门面即：

```text
file_obj
  -> read_source_bytes(...)
  -> pdf.convert_pdf_to_html(source_bytes, filename)
  -> ProcessResult(filename, html)
```

DOCX 分支：

```text
file_obj
  -> read_source_bytes(...) 读取 bytes 并复位文件指针
  -> docx.convert_docx_to_html(source_bytes)
  -> ProcessResult(filename, html)
```
"""

from __future__ import annotations

from pathlib import Path

from service.document_processor.docx import convert_docx_to_html
from service.document_processor.pdf import convert_pdf_to_html
from service.document_processor.schemas import ProcessResult

__all__ = [
    "InvalidFileObjectError",
    "UnsupportedFileTypeError",
    "process",
]

SUPPORTED_FILE_TYPES: dict[str, str] = {
    "pdf": "pdf",
    "docx": "docx",
}


class InvalidFileObjectError(TypeError):
    """当处理器收到非 file-like 对象时抛出。"""


class UnsupportedFileTypeError(ValueError):
    """当输入类型不是 PDF 或 DOCX，或无法确认类型时抛出。"""


# ---------------------------------------------------------------------------
# 入口与类型检测
# ---------------------------------------------------------------------------


def process(file_obj, file_type: str | None = None) -> ProcessResult:
    """把一个 PDF 或 DOCX 文件对象转换成抽取友好的 HTML。"""

    validate_file_obj(file_obj)
    explicit = normalize_file_type(file_type) if file_type is not None else None
    fallback = "document.docx" if explicit == "docx" else "document.pdf"
    filename = resolve_filename(file_obj, fallback=fallback)
    detected = detect_file_type(file_type=file_type, filename=filename)

    if detected == "docx":
        return _process_docx(file_obj, filename)

    return _process_pdf(file_obj, filename)


def validate_file_obj(file_obj) -> None:
    """确保入口收到的是最小可用的 file-like 对象。"""

    read_method = getattr(file_obj, "read", None)
    if not callable(read_method):
        raise InvalidFileObjectError(
            "Expected a file-like object with a callable read() method."
        )


def resolve_filename(file_obj, *, fallback: str = "document.pdf") -> str:
    """从上传对象里取源文件名，缺省时回退为 fallback。"""

    for attr_name in ("filename", "name"):
        value = getattr(file_obj, attr_name, None)
        if isinstance(value, str) and value.strip():
            return Path(value).name
    return fallback


def normalize_file_type(value: str) -> str:
    """把用户传入的文件类型或后缀归一化成小写无点字符串。"""

    return str(value).strip().lower().lstrip(".")


def detect_file_type(*, file_type: str | None, filename: str) -> str:
    """确认输入类型是 PDF 还是 DOCX，返回规范化后的类型字符串。

    显式 file_type 优先；没有显式类型时就退化到文件名后缀。
    两者都无法确认或不在支持列表里时抛出 UnsupportedFileTypeError。
    """

    if file_type is not None:
        normalized = normalize_file_type(file_type)
        if normalized not in SUPPORTED_FILE_TYPES:
            raise UnsupportedFileTypeError(f"Unsupported file type: {file_type!r}.")
        return normalized

    suffix = Path(filename).suffix
    if not suffix:
        raise UnsupportedFileTypeError(
            f"Could not determine file type from filename: {filename!r}."
        )
    normalized = normalize_file_type(suffix)
    if normalized not in SUPPORTED_FILE_TYPES:
        raise UnsupportedFileTypeError(f"Unsupported file type: {suffix!r}.")
    return normalized


def read_source_bytes(file_obj) -> bytes:
    """读取二进制内容，并在支持 seek() 时把指针复位到开头。"""

    if hasattr(file_obj, "seek"):
        file_obj.seek(0)
    source_bytes = file_obj.read()
    if hasattr(file_obj, "seek"):
        file_obj.seek(0)
    return source_bytes


# ---------------------------------------------------------------------------
# 分支编排：只做字节读取与结果拼接，具体转换交给 pdf / docx 子包
# ---------------------------------------------------------------------------


def _process_pdf(file_obj, filename: str) -> ProcessResult:
    """PDF 分支：读取字节并委托给 pdf 子包的单一转换函数。"""

    source_bytes = read_source_bytes(file_obj)
    return ProcessResult(
        filename=filename,
        html=convert_pdf_to_html(source_bytes, filename),
    )


def _process_docx(file_obj, filename: str) -> ProcessResult:
    """DOCX 分支：读取字节并委托给 docx 子包的单一转换函数。"""

    source_bytes = read_source_bytes(file_obj)
    return ProcessResult(
        filename=filename,
        html=convert_docx_to_html(source_bytes),
    )
