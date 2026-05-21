# `test_processor.py`

Tests the public `service.document_processor.processor.process(...)` entry point.

The tests mock MinerU output, then assert PDF validation, filename handling,
byte reading, generated HTML, display HTML, Markdown, md_list, backend blocks,
semantic document output, and processor metadata.

实现步骤：

```text
file_obj
  -> validate_file_obj(...) / validate_pdf_type(...)
  -> read_source_bytes(...) 并复位文件指针
  -> 调用 convert_pdf_bytes_to_content_list(...)，engine=mineru-pipeline
  -> 复用 mineru_html 生成 html / display_html / markdown / blocks / semantic_document
```

测试覆盖：

- `test_process_validates_input_then_calls_pdf_pipeline`：确认无可用文本层时读取源字节、调用 MinerU 分支，并生成完整结果结构。
- `test_process_uses_mineru_even_when_pdf_text_layer_is_readable`：确认即使 PDF 文本层可读，当前主流程仍调用 MinerU，并记录 `engine=mineru-pipeline`。
- 其余测试覆盖显式 PDF 类型、默认文件名、非 PDF 类型和非 file-like 输入的错误处理。
