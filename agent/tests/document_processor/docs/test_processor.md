# `test_processor.py`

Tests the public `service.document_processor.processor.process(...)` entry point.

The tests mock MinerU output, then assert PDF/DOCX type routing, filename
handling, byte reading, and the generated HTML document.

实现步骤：

```text
file_obj
  -> validate_file_obj(...)
  -> detect_file_type(file_type, filename)  显式类型优先，否则看后缀
       ├─ "docx" -> 内部 _process_docx，engine=python-docx
       └─ "pdf"  -> 调用 convert_pdf_bytes_to_content_list(...)，engine=mineru-pipeline
  -> 生成带 CSS 的完整 HTML 文档作为 ProcessResult.html
```

测试覆盖：

- `test_process_validates_input_then_calls_pdf_pipeline`：确认无可用文本层时读取源字节、调用 MinerU 分支，并生成完整 HTML。
- `test_process_uses_mineru_even_when_pdf_text_layer_is_readable`：确认即使 PDF 文本层可读，当前主流程仍调用 MinerU。
- `test_process_accepts_explicit_pdf_type_without_filename_suffix`：显式 `file_type=".PDF"`（去掉文件名后缀）时仍能确认 PDF 并走 MinerU。
- `test_process_routes_docx_explicit_type_to_docx_pipeline`：显式 `file_type="docx"` 时，即使文件名带 `.pdf` 后缀也优先按类型切入 DOCX 分支。
- `test_process_routes_docx_filename_suffix_to_docx_pipeline`：只凭 `.DOCX` 后缀（大写）切入 DOCX 分支。
- `test_process_routes_docx_explicit_type_to_default_docx_filename`：无文件名但显式 `file_type="docx"` 时使用默认文件名 `document.docx` 并走 DOCX 分支。
- `test_process_rejects_unsupported_explicit_type`：显式 `file_type="txt"`（不在支持列表）时抛 `UnsupportedFileTypeError`。
- `test_process_rejects_objects_without_file_like_read_method`：非 file-like 输入抛 `InvalidFileObjectError`。
- `test_process_rejects_non_pdf_filename_when_type_is_omitted`：无显式类型且后缀不支持（如 `.txt`）时抛 `UnsupportedFileTypeError`。
- `test_process_uses_default_pdf_filename_when_name_is_missing`：无文件名且无显式类型时回退为 `document.pdf`。
