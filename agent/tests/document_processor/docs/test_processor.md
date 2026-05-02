# `test_processor.py`

## 基本实现思路

`service.document_processor.processor` 是 PDF 转 HTML 的唯一业务入口。测试固定下面这条链路：

```text
file_obj + file_type
  -> process(...)
  -> validate_file_obj(...)
  -> resolve_filename(...)
  -> validate_pdf_type(...)
  -> read_source_bytes(...)
  -> convert_to_docling_document(...)
  -> export_html(...)
  -> clean_semantic_html(...)
  -> ProcessResult(filename, html)
```

## 测什么

- 公开入口会按顺序校验输入、读取 bytes、调用 docling 转换并返回清理后的语义 HTML fragment。
- 显式 `file_type=".PDF"` 可以绕过非 PDF 文件名后缀。
- 非 file-like 对象会被拒绝。
- 显式非 PDF 类型会被拒绝。
- 未显式传类型时，非 PDF 文件名后缀会被拒绝。
- 没有文件名时会回退为 `document.pdf`。

## 每个函数在干什么

`test_process_validates_input_then_calls_pdf_pipeline`

- 用 fake `convert_to_docling_document(...)` 和 `export_html(...)` 替代真实 docling。
- 调用公开入口 `process(...)`。
- 检查源 bytes、文件名和清理后的 HTML 都沿 pipeline 正确传递。

`test_process_accepts_explicit_pdf_type_without_filename_suffix`

- 构造文件名为 `upload.bin` 的文件对象。
- 显式传入 `file_type=".PDF"`。
- 检查入口仍按 PDF 处理。

`test_process_rejects_objects_without_file_like_read_method`

- 传入普通对象。
- 检查入口抛 `InvalidFileObjectError`。

`test_process_rejects_non_pdf_explicit_type`

- 显式传入 `file_type="docx"`。
- 检查入口抛 `UnsupportedFileTypeError`。

`test_process_rejects_non_pdf_filename_when_type_is_omitted`

- 构造 `.txt` 文件名。
- 不传显式类型。
- 检查入口抛 `UnsupportedFileTypeError`。

`test_process_uses_default_pdf_filename_when_name_is_missing`

- 构造没有 `filename/name` 的内存文件对象。
- 检查入口使用 `document.pdf`。

## 怎么跑

```bash
conda activate agent-gate
python -m pytest tests/document_processor/test_processor.py -q
```
