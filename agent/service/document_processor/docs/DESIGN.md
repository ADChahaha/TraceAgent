# Document Processor Design

这份文档面向开发者，记录 `service.document_processor` 的实现分层、处理链路和设计约束。使用方式请看 [README.md](./agent/service/document_processor/README.md)，调用方 API 契约请看 [API.md](./agent/service/document_processor/docs/API.md)。

## 目标

`service.document_processor` 负责接收原始文档文件对象，对其进行预处理和标准化，并输出后续 `service.file_extraction_agent` 可以直接消费的内容。

这一层的重点不是直接做字段抽取，而是：

- 把原始文件转换成统一的文本块结构
- 在可能的情况下保留原文定位信息
- 为前端高亮和后续抽取同时服务

## 支持的输入

当前设计上支持：

- `pdf`
- `docx`

当前不支持：

- `doc`

输入形式优先为文件对象，而不是路径。

## 接口分层

- 业务接口：`service.document_processor.processor.process(file_obj, file_type=None)`
- route 接口：`agent/routes/document_processor.py`

约束：

- route 层只负责 HTTP 协议适配，不反向定义业务层返回结构
- 业务层不依赖 FastAPI 或 Pydantic
- Python 调用方优先直接使用业务接口，HTTP 调用方通过 route 层访问

## 主链路

```text
file_obj
  -> service.document_processor.processor.process(...)
  -> 外层完成输入校验和文件类型推断
  -> impl/ 内部固定接口类 `InternalProcessorInterface`
  -> 接口类内部注册表按 FileType 选择处理器
  -> `BaseDocumentProcessor` 子类
  -> ProcessResult
```

当前已经落地到代码里的部分是：

- 外层 `process(...)`
- `impl/` 内部固定接口类
- 抽象基类
- 注册机制
- `PDF -> docling -> markdown + blocks` 的真实处理链路
- `DOCX -> python-docx -> markdown + blocks` 的真实处理链路

后续还可以继续细化的部分是：

- `pdf` block 标准化细节
- `pdf` 表格、图片等特殊节点的归一化策略
- markdown 导出细节

## PDF 实现

当前 `PDF` 默认实现入口在 `impl/pdf/processor.py`，可选 PaddleOCR 实现入口在 `impl/pdf/paddle_processor.py`。默认路径仍然是 `docling + RapidOCR`；当启动前设置 `DOCUMENT_PROCESSOR_PDF_ENGINE=pdf-paddle` 时，内部注册表会把 `FileType.PDF` 绑定到 `PdfPaddleProcessor`。

实现步骤：

```text
调用方传入 pdf file_obj
  -> `service.document_processor.processor.process(...)` 先校验 read() 并解析出 FileType.PDF
  -> `InternalProcessorInterface` 从默认注册表里拿到 `PdfProcessor`
  -> `PdfProcessor` 先检查 `DOCLING_CACHE_DIR` / `RAPIDOCR_MODEL_ROOT` / `HF_HOME` 一类环境变量；如果调用方没配，就自动落到 `impl/pdf/models/` 下的模型目录
  -> `PdfProcessor` 再延迟导入 docling 运行时，避免 import 阶段就绑定到开发者本机默认缓存路径
  -> 初始化 `DocumentConverter` 时显式配置 `RapidOcrOptions(backend="torch", lang=["chinese", "english"], rapidocr_params={"Global.model_root_dir": ...})`，把中文 PDF 的文字抽取固定到同一条 OCR 路径，并把 RapidOCR 模型下载到 `impl/pdf/models/rapidocr`
  -> `PdfProcessor` 读取 file_obj 的二进制内容，并从 filename/name 推出输出文件名，没有就回退成 `document.pdf`
  -> 把二进制包装成 `DocumentStream(name, BytesIO(...))`
  -> 调用 `docling.document_converter.DocumentConverter.convert(...)`
  -> 从 `conversion_result.document.export_to_markdown()` 提取整篇 markdown
  -> 遍历 `document.iterate_items()`，把 title/section_header/text/table 等节点压平成 `ContentBlock`
  -> 从 provenance 提取 page_no 和 bbox
  -> 返回 `ProcessResult(file_type, filename, md_list, markdown, blocks, meta_info)`
```

这里的设计约束是：

- 默认 `PDF` 只走 `docling` 这一条解析链路
- 如果默认 `docling` 路径失败，就直接向上抛错，不做任何兜底解析
- 如果调用方没有显式配置模型目录，默认把 docling / Hugging Face / RapidOCR 相关下载产物都放到 `impl/pdf/models/` 下
- PDF 文字抽取当前显式使用 `RapidOCR`，不再依赖 `docling` 的自动 OCR 选择
- 当前 block 归一化优先保留文本、页码和 bbox，不在这一层扩展额外业务字段

可选 PaddleOCR 路径的处理流程是：

```text
调用方传入 pdf file_obj
  -> `InternalProcessorInterface` 读取 `DOCUMENT_PROCESSOR_PDF_ENGINE`
  -> 如果值为 `pdf-paddle` / `paddleocr` / `paddle`，选择 `PdfPaddleProcessor`
  -> `PdfPaddleProcessor` 复用默认 PDF helper 读取文件名和二进制
  -> 如果调用方没设置 `PADDLE_PDX_CACHE_HOME`，先把 PaddleX 缓存收口到 `impl/pdf/models/paddlex`
  -> 用 `pypdfium2` 将 PDF 每页渲染成图片
  -> 初始化 `paddleocr.PPStructureV3(lang="ch", ocr_version="PP-OCRv4", use_table_recognition=True, format_block_content=True, ...)`
  -> 逐页调用 PaddleOCR 3.x 的 `predict(...)` 接口
  -> 从结构化结果读取 `markdown_texts` 作为每页 markdown
  -> 从 `parsing_res_list` 读取版面块，表格转 `ContentBlock(kind="table")`，普通文字转 `ContentBlock(kind="text")`
  -> 如果运行时只返回普通 OCR `rec_texts / rec_boxes`，才降级成 `ContentBlock(kind="text_line")`
  -> 按页拼接 `md_list`，再合并成整篇 markdown
  -> 返回 `ProcessResult(meta_info.ocr_engine="paddleocr", meta_info.paddle_pipeline="PPStructureV3")`
```

PaddleOCR 路径不依赖 docling，也不读取 docling/RapidOCR 缓存目录；它要求运行环境额外安装 `agent-service[paddle]` 依赖。默认初始化 PaddleOCR PPStructureV3 时会关闭文档方向分类、文档矫正和文本行方向分类，启用表格识别，并使用 `PP-OCRv4` mobile 模型，先把速度控制在可接受范围内。如果需要更高精度但更慢的 PP-OCRv5，可通过 `DOCUMENT_PROCESSOR_PADDLE_OCR_VERSION=PP-OCRv5` 覆盖。这个路径主要用于对比密集表格 PDF 的 OCR 质量，默认不替代现有 docling 路径。

## DOCX 实现

当前 `DOCX` 已经落地为单一路径实现，入口在 `impl/docx/processor.py`。

实现步骤：

```text
调用方传入 docx file_obj
  -> `service.document_processor.processor.process(...)` 先校验 read() 并解析出 FileType.DOCX
  -> `InternalProcessorInterface` 从默认注册表里拿到 `DocxProcessor`
  -> `DocxProcessor` 读取 file_obj 的二进制内容，并从 filename/name 推出输出文件名
  -> 用 `python-docx` 的 `Document(BytesIO(...))` 直接打开文档
  -> 按 body 的真实顺序遍历 paragraph/table
  -> heading 段落转标题 markdown，普通段落转正文 markdown，表格转简单 markdown table
  -> 同时把标题、正文、表格行归一化成 `ContentBlock`
  -> 返回 `ProcessResult(file_type, filename, md_list, markdown, blocks, meta_info)`
```

这里的设计约束是：

- `DOCX` 解析固定走 `python-docx`
- 处理器不依赖本机 LibreOffice 之类的外部桌面应用
- 当前 block 主要保留段落样式名、表格行文本这类结构信息，不依赖坐标系

## 目录职责

- `processor.py`
  - 对外统一入口
  - 负责外层编排
  - 负责输入校验和文件类型推断
  - 把处理请求转交给 `impl/` 内部固定接口类
- `schemas.py`
  - 统一结果结构
- `types.py`
  - 文件类型和推断逻辑
- `impl/`
  - `base.py`：具体文件处理器的抽象基类
  - `interface.py`：内部固定接口类和注册机制
  - 固定接口类只负责按已确定的 `FileType` 查找处理器并调用
  - 具体文件处理器继承 `BaseDocumentProcessor`
  - 由内部固定接口类自己维护处理器注册机制
- `impl/pdf/`
  - `processor.py`：基于 `docling` 的 PDF 处理器
  - 只负责 `PDF` 的二进制读取、`DocumentStream` 包装、docling 调用和 block 归一化
- `impl/docx/`
  - `processor.py`：基于 `python-docx` 的 DOCX 处理器
  - 只负责 `DOCX` 的二进制读取、段落/表格遍历、markdown 导出和 block 归一化
- `docs/`
  - `API.md`：面向调用方的 Python / HTTP 入口、请求字段、返回结构和失败语义
  - `DESIGN.md`：面向开发者的模块边界、处理链路和设计约束
  - `DEVLOG.md`：按时间记录重要变更

## 重命名说明

该模块原名为 `ocr_processor`，但实际职责已经超出 OCR，本次统一改名为 `service.document_processor`，以突出“文档标准化”而不是单一 OCR 技术细节。
