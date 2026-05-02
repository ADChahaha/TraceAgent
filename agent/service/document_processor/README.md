# Document Processor

`service.document_processor` 只负责把 PDF 文件对象交给 docling，并返回抽取友好的语义 HTML fragment。

## 支持的输入

- 支持：`pdf`
- 不支持：`docx`、`doc`、路径字符串

调用方应传入已打开的二进制文件对象，而不是文件路径。

## Usage

更完整的调用方接口说明见 [`docs/API.md`](docs/API.md)。

```python
from service.document_processor.processor import process

result = process(file_obj, file_type=None)

print(result.filename)
print(result.html)
```

HTTP 入口：

- `POST /v1/document-processor/process`
- 兼容旧路径：`POST /v1/ocr/process`

## 实现链路

```text
PDF file_obj
  -> process(file_obj, file_type)
  -> validate_file_obj(file_obj)
  -> resolve_filename(file_obj)
  -> validate_pdf_type(file_type, filename)
  -> read_source_bytes(file_obj)
  -> convert_to_docling_document(source_bytes, filename)
  -> export_html(document)
  -> clean_semantic_html(raw_html)
  -> ProcessResult(filename, html)
```

也就是说：

- `processor.py` 只承载入口校验、读 bytes 和主 pipeline 编排。
- `docling_converter.py` 承载 docling 调用、语义 label 过滤和运行时缓存配置。
- `html_cleaner.py` 删除页面壳和装饰属性，并为关键节点补 `id`。
- `schemas.py` 只定义 `ProcessResult(filename, html)`。
- 当前没有 `impl/`、`types.py`、处理器注册表或 DOCX/Paddle/Marker 分支。

## PDF 配置速查

默认链路：

```text
PDF bytes
  -> docling DocumentConverter
  -> RapidOCR
  -> document.export_to_html(labels=...)
  -> clean semantic HTML fragment
```

docling 导出时只保留 `TITLE`、`SECTION_HEADER`、`TEXT`、`PARAGRAPH`、`LIST_ITEM`、`TABLE` 和 `CAPTION` 这些 label。后处理不会再二次判断标签是否有意义，只删除 `html/head/body/style/script/meta` 页面壳和 `class/style/data-*` 等装饰属性；保留属性包括 `id`、`rowspan` 和 `colspan`。

docling 的 `export_to_html(...)` 可以用 `labels` 控制导出哪些文档元素，但当前版本不会把每个元素的 `DocItemLabel` 原生写成 HTML `class` 或 `data-*`。因此本模块不伪造 `data-dp-type`，避免让调用方误以为这是 docling 的真实 label。

表格结构以 docling 输出为准。`html_cleaner.py` 会保留空单元格和 `rowspan/colspan`，只给 `table/tr` 补定位 id，不给 `td/th` 自动补 id，也不会根据表头和正文列数差异猜测补列或删列。表头单元格数量少不一定是错误，可能是合法的 `colspan/rowspan`；展开后仍不一致时通常代表 PDF 表格识别阶段已经存在偏差。

常用环境变量：

| 环境变量 | 默认值 | 作用 |
| --- | --- | --- |
| `DOCUMENT_PROCESSOR_RAPIDOCR_BACKEND` | `onnxruntime` | RapidOCR 后端，支持 `onnxruntime`、`openvino`、`paddle`、`torch`。 |
| `DOCUMENT_PROCESSOR_RAPIDOCR_ONNX_USE_COREML` | `0` | 仅 onnxruntime 后端使用，是否尝试 CoreML。 |
| `DOCUMENT_PROCESSOR_RAPIDOCR_TORCH_USE_MPS` | 跟随 `DOCUMENT_PROCESSOR_DOCLING_DEVICE=mps` | 仅 torch 后端使用，是否尝试 MPS。 |
| `DOCUMENT_PROCESSOR_RAPIDOCR_FORCE_FULL_PAGE_OCR` | `0` | 设为 `1` 时忽略 PDF 内置文本层并整页 OCR。 |
| `DOCUMENT_PROCESSOR_PDF_TABLE_DO_CELL_MATCHING` | `1` | docling 表格 cell matching 开关。 |
| `DOCUMENT_PROCESSOR_DOCLING_DEVICE` | docling 默认值 | 传给 docling `AcceleratorOptions.device`。 |
| `DOCUMENT_PROCESSOR_DOCLING_NUM_THREADS` | docling 默认值 | 传给 docling `AcceleratorOptions.num_threads`，必须是正整数。 |
| `DOCUMENT_PROCESSOR_PDF_OCR_BATCH_SIZE` | docling 默认值 | 传给 docling `ocr_batch_size`，必须是正整数。 |
| `DOCUMENT_PROCESSOR_PDF_LAYOUT_BATCH_SIZE` | docling 默认值 | 传给 docling `layout_batch_size`，必须是正整数。 |
| `DOCUMENT_PROCESSOR_PDF_TABLE_BATCH_SIZE` | docling 默认值 | 传给 docling `table_batch_size`，必须是正整数。 |

模型和缓存目录默认会收口到 `service/document_processor/models/` 下：

| 环境变量 | 未设置时的默认目录 |
| --- | --- |
| `DOCLING_CACHE_DIR` | `models/docling` |
| `RAPIDOCR_MODEL_ROOT` | `models/rapidocr` |
| `HF_HOME` | `models/huggingface` |

如果外部已经设置 `HF_HOME`、`HF_HUB_CACHE` 或 `HUGGINGFACE_HUB_CACHE`，处理器不会覆盖 Hugging Face 缓存目录。
