# Document Processor Design

这份文档面向开发者，记录 `service.document_processor` 的实现链路、函数职责和设计约束。调用方 API 契约见 [API.md](./agent/service/document_processor/docs/API.md)。

## 目标

`service.document_processor` 只负责把 PDF 文件对象转换成抽取友好的语义 HTML fragment：

```text
PDF file_obj
  -> docling
  -> semantic HTML fragment
```

它不做字段抽取，不生成 blocks，不支持 DOCX，也不维护多处理器注册机制。

## 主链路

完整 pipeline：

```text
调用方传入 file_obj，可选传 file_type
  -> processor.process(file_obj, file_type)
  -> validate_file_obj(file_obj)
  -> resolve_filename(file_obj)
  -> validate_pdf_type(file_type, filename)
  -> read_source_bytes(file_obj)
  -> convert_to_docling_document(source_bytes, filename)
  -> export_html(document)
  -> clean_semantic_html(raw_html)
  -> ProcessResult(filename, html)
```

目录保持极简：

```text
service/document_processor/
├── __init__.py
├── processor.py
├── schemas.py
├── docling_converter.py
├── html_cleaner.py
├── README.md
└── docs/
    ├── API.md
    ├── DESIGN.md
    └── DEVLOG.md
```

`models/` 只作为 docling、RapidOCR 和 Hugging Face 的运行时缓存目录，由 `configure_runtime_cache_dirs()` 按需创建，不是需要维护的源码文件树。

## `schemas.py`

### `ProcessResult`

处理完成后的唯一结果结构。

```text
filename + html
  -> ProcessResult(filename=filename, html=html)
```

字段：

- `filename`：源文件基名，没有源文件名时为 `document.pdf`。
- `html`：清理后的语义 HTML fragment。

这里不保留 `file_type`、`blocks`、`meta_info` 或 `warnings`。当前模块只有 PDF 一种输入，错误也采用 fail-fast 方式直接抛出异常。

## `processor.py`

### `process(file_obj, file_type=None)`

对外唯一业务入口。

```text
file_obj + file_type
  -> validate_file_obj(file_obj)
  -> filename = resolve_filename(file_obj)
  -> validate_pdf_type(file_type=file_type, filename=filename)
  -> source_bytes = read_source_bytes(file_obj)
  -> document = convert_to_docling_document(source_bytes, filename)
  -> raw_html = export_html(document)
  -> html = clean_semantic_html(raw_html)
  -> ProcessResult(filename, html)
```

失败行为：

- 输入不可读时抛 `InvalidFileObjectError`。
- 类型不是 PDF 时抛 `UnsupportedFileTypeError`。
- docling 失败时透传底层异常。

### `validate_file_obj(file_obj)`

输入是任意对象。

```text
file_obj
  -> 读取 read 属性
  -> 如果 read 不可调用，抛 InvalidFileObjectError
  -> 否则返回 None
```

这个函数只验证最小 file-like 契约，不读取内容，也不判断文件类型。

### `resolve_filename(file_obj)`

输入是已通过 `read()` 校验的文件对象。

```text
file_obj
  -> 依次读取 file_obj.filename 和 file_obj.name
  -> 找到非空字符串就用 Path(...).name 取基名
  -> 如果都没有，返回 document.pdf
```

它不判断后缀是否合法；PDF 类型校验由 `validate_pdf_type(...)` 负责。

### `validate_pdf_type(file_type, filename)`

输入是可选显式类型和已解析文件名。

```text
file_type + filename
  -> 如果 file_type 不为空，normalize_file_type(file_type)
  -> 显式类型不是 pdf 时抛 UnsupportedFileTypeError
  -> 如果 file_type 为空，读取 filename 后缀
  -> 后缀为空或不是 .pdf 时抛 UnsupportedFileTypeError
  -> PDF 通过时返回 None
```

### `normalize_file_type(value)`

输入是字符串类型或后缀。

```text
value
  -> str(value)
  -> strip()
  -> lower()
  -> lstrip(".")
  -> normalized string
```

它只做字符串归一化，不决定是否支持。

### `read_source_bytes(file_obj)`

输入是已校验可读的文件对象。

```text
file_obj
  -> 如果有 seek()，先 seek(0)
  -> 调用 read() 读取完整 bytes
  -> 如果有 seek()，再 seek(0)
  -> 返回 source_bytes
```

这个函数不验证 PDF 魔数，类型判断只看显式 `file_type` 或文件名后缀。

### `convert_to_docling_document(source_bytes, filename)`

输入是 PDF 二进制和文件名。

```text
source_bytes + filename
  -> load_docling_runtime()
  -> build_document_converter()
  -> DocumentStream(name=filename, stream=BytesIO(source_bytes))
  -> converter.convert(stream)
  -> conversion_result.document
```

docling 解析失败时不兜底，异常直接向上抛出。

## `docling_converter.py`

这个文件承载全部 docling 运行时、PDF pipeline 配置和 HTML 导出细节，避免 `processor.py` 变成具体实现文件。

```text
source_bytes + filename
  -> convert_to_docling_document(source_bytes, filename)
  -> load_docling_runtime()
  -> build_document_converter()
  -> DocumentStream(name=filename, stream=BytesIO(source_bytes))
  -> converter.convert(...)
  -> conversion_result.document
```

### `export_html(document)`

输入是 docling document。

```text
document
  -> 读取 document.export_to_html
  -> 不可调用时抛 TypeError
  -> 调用 export_to_html(labels=semantic_docling_labels(), include_annotations=False)
  -> 返回值不是 str 时抛 TypeError
  -> 返回 raw_html
```

### `semantic_docling_labels()`

返回 docling HTML 导出阶段保留的文档 label：

```text
TITLE / SECTION_HEADER / TEXT / PARAGRAPH / LIST_ITEM / TABLE / CAPTION
  -> export_to_html(labels=...)
```

这一步先在 docling 层过滤掉图片、页眉页脚、公式、脚注等当前抽取不需要的文档元素。

## `html_cleaner.py`

### `clean_semantic_html(html, id_prefix="dp")`

把 docling 原始 HTML 清理成字段抽取直接消费的 fragment。它不再决定哪些文档内容有意义；内容筛选由 `docling_converter.export_html(... labels=...)` 完成。

```text
docling raw html
  -> HtmlFragmentParser 解析成轻量节点树
  -> clean_children(...) 递归处理节点
  -> clean_node(...) 展开 html/body，其他 docling 输出标签原样保留
  -> clean_attrs(...) 删除装饰属性，只保留 id/rowspan/colspan
  -> assign_ids(...) 为缺少 id 的段落、列表、表格、表格行等块级节点补 dp-* id
  -> serialize_fragment(...) 输出 HTML fragment
```

标签策略：

- `html/body` 只作为页面壳展开。
- `head/style/script/noscript/meta/link` 删除。
- 其他标签不在 cleaner 里二次筛选，按 docling 的 `labels` 输出保留。

保留属性：

- `id`
- `rowspan`
- `colspan`

不保留 `class/style/data-*` 等装饰属性。这个文件只做 HTML 清洁和定位 id，不做文档语义判断。

表格定位粒度固定到行：`table` 和 `tr` 会自动补 id，`td/th` 不自动补 id。`td/th` 只保留来源 HTML 已经存在的 `id`，以及用于合并单元格的 `rowspan/colspan`。

表格数量异常不在 cleaner 中修复：

```text
docling 输出 table
  -> 保留 tr/th/td 和空单元格
  -> 保留 rowspan/colspan
  -> 删除装饰属性
  -> 不根据表头和正文列数猜测补列或删列
```

这样做是为了避免后处理破坏 docling 已经识别正确的合并表头。调用方需要判断表格是否异常时，应先按 `rowspan/colspan` 展开成二维矩阵，再比较展开后的列宽。

当前也不输出 `data-dp-type`。docling 的 `export_to_html(labels=...)` 能按 `DocItemLabel` 过滤导出内容，但当前安装版本不会把每个元素的 label 原生写到 HTML 属性里；本模块不从 `h1/p/table` 等标签反推 label，避免伪造来源语义。

### `build_document_converter()`

负责创建带 PDF 配置的 docling `DocumentConverter`。

```text
load_docling_runtime()
  -> build_pdf_pipeline_options(...)
  -> DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(...)})
```

### `load_docling_runtime()`

负责延迟导入 docling 运行时类。

```text
configure_runtime_cache_dirs()
  -> 导入 DocumentStream / DocumentConverter / InputFormat
  -> 导入 PdfFormatOption / PdfPipelineOptions / RapidOcrOptions
  -> 导入 AcceleratorOptions / TableStructureOptions
  -> 返回这些 runtime class
```

延迟导入的原因是先设置缓存目录，避免 docling/RapidOCR/Hugging Face 产物散落到用户目录。

### `build_pdf_pipeline_options(...)`

负责组装 docling PDF pipeline。

```text
pdf pipeline classes
  -> build_accelerator_options(...)
  -> build_table_structure_options(...)
  -> build_rapidocr_params(...)
  -> resolve_rapidocr_backend()
  -> pdf_batch_options_from_env()
  -> PdfPipelineOptions(...)
```

当前固定开启表格结构识别，HTML 导出仍由 docling document 完成。

### `build_accelerator_options(accelerator_options_cls)`

读取：

- `DOCUMENT_PROCESSOR_DOCLING_DEVICE`
- `DOCUMENT_PROCESSOR_DOCLING_NUM_THREADS`

线程数必须是正整数，否则抛 `ValueError`。

### `build_table_structure_options(table_structure_options_cls)`

读取 `DOCUMENT_PROCESSOR_PDF_TABLE_DO_CELL_MATCHING`。

```text
环境变量未设置
  -> 默认 True
设置为 1/true/yes/on
  -> True
其他
  -> False
```

### `build_rapidocr_params(accelerator_options)`

返回 RapidOCR 运行参数：

- `Global.model_root_dir` 指向 `models/rapidocr`
- `EngineConfig.onnxruntime.use_coreml`
- `EngineConfig.torch.use_mps`

### `resolve_rapidocr_backend()`

读取 `DOCUMENT_PROCESSOR_RAPIDOCR_BACKEND`，默认 `onnxruntime`。

只接受：

- `onnxruntime`
- `openvino`
- `paddle`
- `torch`

非法值抛 `ValueError`。

### `pdf_batch_options_from_env()`

读取并返回 docling batch 配置：

- `DOCUMENT_PROCESSOR_PDF_OCR_BATCH_SIZE`
- `DOCUMENT_PROCESSOR_PDF_LAYOUT_BATCH_SIZE`
- `DOCUMENT_PROCESSOR_PDF_TABLE_BATCH_SIZE`

空值不写入 options；非正整数抛 `ValueError`。

### `parse_positive_int(env_name, raw_value)`

把字符串解析成正整数。

```text
raw_value
  -> int(raw_value)
  -> value >= 1
  -> 返回 value
```

失败时抛 `ValueError`，错误消息包含环境变量名。

### `env_flag(name, default)`

解析布尔环境变量。

```text
未设置
  -> default
1/true/yes/on
  -> True
其他
  -> False
```

### `configure_runtime_cache_dirs()`

把默认缓存收口到 `service/document_processor/models/`。

```text
package_models_root()
  -> 未设置 DOCLING_CACHE_DIR 时设为 models/docling
  -> 未设置 RAPIDOCR_MODEL_ROOT 时设为 models/rapidocr
  -> 未设置 HF_HOME/HF_HUB_CACHE/HUGGINGFACE_HUB_CACHE 时设为 models/huggingface
  -> 创建这些目录
```

### `package_models_root()`

返回 `processor.py` 同级的 `models/` 目录。

### `resolve_rapidocr_rec_keys_path()`

只在 `models/rapidocr/ppocr_keys_v1.txt` 存在时返回路径，否则返回 `None`。

### `resolve_docling_artifacts_path()`

返回 capabilities 接口展示用的 docling 缓存目录。

```text
如果 DOCLING_CACHE_DIR 已设置
  -> 返回该路径
否则
  -> 返回 models/docling
```

## Route 边界

`routes/document_processor.py` 只做 HTTP 协议适配：

```text
UploadFile
  -> UploadFileProxy
  -> service.document_processor.processor.process(...)
  -> ProcessResult
  -> ProcessResponse(filename, html)
```

route 层不导入 `impl`，也不重新定义业务处理流程。

## 设计约束

- 只支持 PDF。
- 只使用 docling。
- 只返回 HTML。
- 不保留 `impl/`、`types.py`、注册表、DOCX、Paddle 或 Marker 分支。
- 不返回 `markdown`、`md_list`、`blocks`、`meta_info` 或 `warnings`。
