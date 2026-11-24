# 入口分流、共享辅助函数与目录布局

返回 [Document Processor 设计](../DESIGN.md)。

## 目录结构

```text
document_service/document_processor/
|-- __init__.py
|-- processor.py
|-- schemas.py
|-- pdf/
|   |-- __init__.py
|   |-- converter.py
|   \-- html.py
|-- docx/
|   |-- __init__.py
|   \-- docx_processor.py
|-- README.md
\-- docs/
    |-- API.md
    |-- DESIGN.md
    |-- DEVLOG.md
    \-- design/
```

## `processor.py` 公开入口与辅助函数

`processor.py` 是唯一公开入口，负责共享校验函数与 `pdf`/`docx` 子包分流，不直接解析 DOCX 或驱动 MinerU，只读 bytes 并装配 `ProcessResult`。除本入口与 `schemas.ProcessResult` 外，包内其他符号供内部使用。

共享入口辅助函数集中放在 `processor.py`（不另建 `common` 模块）：

- `InvalidFileObjectError`、`UnsupportedFileTypeError`：边界校验异常。
- `validate_file_obj(file_obj)`：校验对象具备可调用的 `read()`。
- `resolve_filename(file_obj, *, fallback)`：依次取 `filename`、`name`，否则回退 `fallback`（显式 `file_type` 为 `docx` 时缺省 `document.docx`，否则 `document.pdf`）。
- `normalize_file_type(value)`：转小写并去除前导点号。
- `detect_file_type(file_type, filename)`：显式 `file_type` 优先，否则按文件名后缀判断，返回 `"pdf"` 或 `"docx"`，否则抛 `UnsupportedFileTypeError`。
- `read_source_bytes(file_obj)`：读取 bytes 并在支持时复位文件指针。

## 引擎分流

- `process(file_obj, file_type=None)` 完成校验、文件名解析与类型检测后，一次性分流至 `_process_pdf`（`engine="mineru-pipeline"`）或 `_process_docx`（`engine="python-docx"`）。
- `docx` 只走 `python-docx`，`pdf` 只走 MinerU 管线；子包内部不再重复判断类型。
