# `test_pdf_processor.py`

## 基本实现思路

这个测试文件覆盖 `service.document_processor.docling_converter` 中与 docling PDF 转换直接相关的 helper。当前不再有 `impl/pdf/processor.py`，docling 运行时和 PDF 转换逻辑集中在 `docling_converter.py`，`processor.py` 只负责串 pipeline。

核心链路：

```text
PDF bytes + filename
  -> convert_to_docling_document(...)
  -> build_document_converter()
  -> load_docling_runtime()
  -> DocumentStream(name, BytesIO(bytes))
  -> DocumentConverter.convert(...)
  -> export_html(document)
```

## 测什么

- PDF bytes 会被包装成 docling `DocumentStream`，并保留源文件名。
- `export_html(...)` 调用 docling `export_to_html(...)`，并要求 docling 只导出标题、段落、列表、表格和 caption 等语义 label。
- `export_html(...)` 会拒绝非字符串返回值。
- docling converter 初始化时开启表格结构识别。
- RapidOCR 明确配置为中文/英文和默认 `onnxruntime` 后端。
- PDF runtime 环境变量能影响整页 OCR、表格 cell matching、device、线程和 batch 参数。
- 文件读取 helper 会复位文件指针。
- docling 异常不会被兜底吞掉。
- 默认缓存目录收口到 `service/document_processor/models/`。
- 显式缓存环境变量不会被覆盖。

## 每个函数在干什么

`test_convert_to_docling_document_wraps_pdf_bytes_and_filename`

- 用 fake `DocumentConverter` 替代真实 docling converter。
- 调用 `convert_to_docling_document(...)`。
- 检查传给 converter 的 `DocumentStream.name` 和 bytes。

`test_export_html_returns_docling_html`

- 构造 fake document。
- 检查 `export_html(...)` 返回 `export_to_html()` 的字符串结果。

`test_export_html_rejects_non_string_docling_output`

- 构造返回 `None` 的 fake document。
- 检查 `export_html(...)` 抛 `TypeError`。

`test_build_document_converter_enables_table_structure`

- 构造 converter。
- 检查 PDF pipeline 中 `do_table_structure=True`。

`test_build_document_converter_uses_explicit_rapidocr`

- 构造 converter。
- 检查 OCR 配置是 `RapidOcrOptions`，后端默认为 `onnxruntime`，语言为中文和英文，模型目录指向 `models/rapidocr`。

`test_build_document_converter_accepts_pdf_runtime_env_overrides`

- 设置整页 OCR、表格 cell matching、device、线程和 batch 环境变量。
- 检查这些值进入 docling PDF pipeline。

`test_read_source_bytes_restores_file_position`

- 从非开头位置读取内存文件。
- 检查返回完整 bytes，并把指针复位到 0。

`test_docling_errors_propagate_without_fallback`

- 用始终抛错的 fake converter 替代 docling。
- 检查异常原样向上抛出。

`test_configure_runtime_cache_dirs_sets_repo_local_defaults`

- 清空相关缓存环境变量。
- 检查默认路径落到 `models/docling`、`models/rapidocr` 和 `models/huggingface`。

`test_configure_runtime_cache_dirs_respects_explicit_overrides`

- 设置自定义缓存目录。
- 检查处理器不会覆盖用户配置。

## 怎么跑

```bash
conda activate agent-gate
python -m pytest tests/document_processor/test_pdf_processor.py -q
```
