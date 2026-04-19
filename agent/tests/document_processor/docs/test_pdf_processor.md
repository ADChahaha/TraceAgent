# `test_pdf_processor.py`

## 基本实现思路

`impl/pdf/processor.py` 是 `document_processor` 里真正负责 PDF 标准化的实现文件。它的目标不是自己解析版面，而是把 PDF 二进制包装成 `docling` 能接受的 `DocumentStream`，再把 `docling` 产出的文档对象归一化成仓库内部统一的 `ProcessResult`。

当前这条处理链路的 pipeline 是：

```text
调用方传入 pdf file_obj
  -> `PdfProcessor.process(...)`
  -> 基类校验 read()
  -> 先检查 `DOCLING_CACHE_DIR` / `RAPIDOCR_MODEL_ROOT` / `HF_HOME`，没配就默认写到 `impl/pdf/models/` 目录
  -> 再延迟导入 docling 运行时
  -> 读取 PDF 二进制并解析 filename/name，没有就回退到 `document.pdf`
  -> 构造 `DocumentStream(name, BytesIO(bytes))`
  -> 调用 `DocumentConverter.convert(...)`
  -> 从 `document.export_to_markdown()` 提取 markdown
  -> 遍历 `document.iterate_items()` 归一化成 `ContentBlock`
  -> 返回 `ProcessResult(file_type, filename, md_list, markdown, blocks, meta_info)`
```

这里最关键的约束有两个：

1. `PDF` 默认实现必须走 `docling`，而不是继续停留在占位 warning。
2. `docling` 的输出要被压平成仓库统一的 markdown + block 结果，方便后续抽取链路直接消费。
3. 没有显式环境变量时，模型目录默认收口到 `impl/pdf/models/`，而不是开发者本机的默认缓存路径。
4. PDF 文字抽取默认显式走 `RapidOCR`，不再依赖 `docling` 自动选择 OCR 后端。
5. `RapidOCR` 模型目录也必须显式落到 `impl/pdf/models/rapidocr`，不能继续落到 `site-packages`。

## 测什么

- `PdfProcessor` 会调用 `docling` 转换 PDF，并生成 markdown 与 blocks
- 当输入对象没有 `filename/name` 时，`PdfProcessor` 会补默认文件名 `document.pdf`
- 顶层 `document_processor.process(...)` 在默认注册表里会把 `pdf` 路由到真正的 `PdfProcessor`
- `docling` 转换失败时，`PdfProcessor` 会直接抛出原始异常，不做任何降级或替代解析
- 如果调用方没有显式配置模型目录，`PdfProcessor` 会默认把运行时模型目录指到 `impl/pdf/models/` 下
- 如果调用方显式设置了缓存环境变量，`PdfProcessor` 不会覆盖这些配置
- 当 `docling` 某些节点的 `export_to_markdown(...)` 需要显式传入 `document` 时，`PdfProcessor` 也能兼容这类接口
- `PdfProcessor` 会显式使用 `RapidOCR` 做文字抽取，而不是继续用 `OcrAutoOptions`
- `PdfProcessor` 会把 `RapidOCR` 的 `model_root_dir` 显式指到 `impl/pdf/models/rapidocr`

## 每个函数在干什么

`test_pdf_processor_uses_docling_to_generate_markdown_and_blocks`

- 用 monkeypatch 把 `DocumentConverter` 替换成可控 fake。
- 直接调用 `PdfProcessor().process(...)`。
- 检查传给 `docling` 的是带文件名的内存流，并确认返回结果里的 markdown、blocks、页码和 bbox 都被正确归一化；其中也覆盖了需要 `document` 参数的节点 markdown 导出。

`test_pdf_processor_passes_document_when_item_markdown_export_requires_it`

- 构造一个 `export_to_markdown(doc)` 形式的 fake 节点。
- 直接调用 `PdfProcessor._extract_text(...)`。
- 检查处理器会把当前 `document` 传进去，而不是假定所有节点导出函数都是零参数。

`test_pdf_processor_uses_explicit_rapidocr_for_text_extraction`

- 用 monkeypatch 把 `DocumentConverter` 替换成 fake。
- 直接实例化 `PdfProcessor()`，读取传给 `DocumentConverter` 的 pipeline 配置。
- 检查 OCR 选项已经显式切成 `RapidOcrOptions(backend="torch", lang=["chinese", "english"])`，并且 `rapidocr_params["Global.model_root_dir"]` 与 `rec_keys_path` 都已经指向 `impl/pdf/models/rapidocr`。

`test_pdf_processor_uses_default_filename_when_input_has_no_name`

- 构造一个没有 `filename/name` 的 PDF 内存流。
- 调用 `PdfProcessor().process(...)`。
- 检查传给 `docling` 的 `DocumentStream.name` 和最终 `ProcessResult.filename` 都会回退成 `document.pdf`。

`test_process_routes_pdf_files_to_docling_processor_by_default`

- 清空 `InternalProcessorInterface` 的默认注册状态。
- 直接走顶层 `document_processor.process(...)` 处理 `.pdf` 文件。
- 检查默认注册表最终绑定的是 `PdfProcessor`，而不是旧的占位处理器。

`test_pdf_processor_propagates_docling_errors_without_fallback`

- 用 monkeypatch 把 `DocumentConverter` 替换成始终抛错的 fake。
- 直接调用 `PdfProcessor().process(...)`。
- 检查 `docling` 的异常会原样向外冒泡，确保实现里没有任何兜底路径。

`test_pdf_processor_sets_repo_local_cache_dirs_by_default`

- 清空 `DOCLING_CACHE_DIR`、`RAPIDOCR_MODEL_ROOT`、`HF_HOME` 和 Hugging Face 相关缓存环境变量。
- 调用运行时缓存目录初始化逻辑。
- 检查默认值会被收口到 `impl/pdf/models/docling`、`impl/pdf/models/rapidocr` 和 `impl/pdf/models/huggingface`。

`test_pdf_processor_respects_explicit_cache_env_overrides`

- 先显式设置自定义 `DOCLING_CACHE_DIR`、`RAPIDOCR_MODEL_ROOT` 和 `HF_HOME`。
- 再调用运行时缓存目录初始化逻辑。
- 检查处理器不会把这些显式配置覆盖回仓库默认目录。

## 为什么有它

这个测试文件专门把 `PDF -> docling -> ProcessResult` 这条真实处理链路钉住。这样后面即使继续补充更细的 block 归一化策略，也不会把“默认 PDF 处理器必须真实接入 docling”这个关键约束退回成占位实现。

## 怎么跑

```bash
source <conda-env>/etc/profile.d/conda.sh
conda activate agent-gate
python -m pytest tests/document_processor/test_pdf_processor.py -q
```
