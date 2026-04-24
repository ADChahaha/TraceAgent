"""文档处理入口的文件类型归一化工具。

实现步骤：

```text
调用方传入 file_obj，可选再传 file_type
  -> 如果显式传了 file_type，就优先用它，不看文件名
  -> 先把这个值去空白、转小写、去掉前导点，例如 ".PDF" -> "pdf"
  -> 如果没传 file_type，就尝试从 file_obj.filename 或 file_obj.name 里取后缀
  -> 再把后缀做同样的归一化，只接受 "pdf" 和 "docx"
  -> 成功时返回内部统一枚举 FileType.PDF / FileType.DOCX
  -> 失败时抛出 UnsupportedFileTypeError，告诉上层是“类型不支持”还是“根本无法判断类型”
```
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path


class UnsupportedFileTypeError(ValueError):
    """在 document_processor 无法确定支持的文件类型时抛出。"""


class FileType(str, Enum):
    PDF = "pdf"
    DOCX = "docx"


def infer_file_type(file_obj, file_type: str | FileType | None = None) -> FileType:
    """根据显式类型或文件名解析统一的文件类型。"""

    if file_type is not None:
        return _parse_file_type(file_type)

    filename = _extract_filename(file_obj)
    if filename is None:
        raise UnsupportedFileTypeError(
            "Could not determine file type: missing explicit file_type and filename."
        )

    suffix = Path(filename).suffix
    if not suffix:
        raise UnsupportedFileTypeError(
            f"Could not determine file type from filename: {filename!r}."
        )
    return _parse_file_type(suffix)


def _parse_file_type(value: str | FileType) -> FileType:
    if isinstance(value, FileType):
        return value

    normalized = str(value).strip().lower().lstrip(".")
    try:
        return FileType(normalized)
    except ValueError as exc:
        raise UnsupportedFileTypeError(f"Unsupported file type: {value!r}.") from exc


def _extract_filename(file_obj) -> str | None:
    for attr_name in ("filename", "name"):
        value = getattr(file_obj, attr_name, None)
        if isinstance(value, str) and value.strip():
            return value
    return None
