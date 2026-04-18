# Document Processor Design

这份文档面向开发者，记录 `document_processor` 的实现分层、处理链路和设计约束。使用方式请看 [README.md](./agent/document_processor/README.md)。

## 目标

`document_processor` 负责接收原始文档文件对象，对其进行预处理和标准化，并输出后续 `file_extraction` 可以直接消费的内容。

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

- 业务接口：`document_processor.processor.process(file_obj, file_type=None)`
- route 接口：`agent/routes/document_processor.py`

约束：

- route 层只负责 HTTP 协议适配，不反向定义业务层返回结构
- 业务层不依赖 FastAPI 或 Pydantic
- Python 调用方优先直接使用业务接口，HTTP 调用方通过 route 层访问

## 主链路

```text
file_obj
  -> document_processor.process(...)
  -> ProcessorDispatcher
  -> PdfProcessor / DocProcessor
  -> normalized ContentBlock list
  -> markdown export
  -> ProcessResult
```

## 目录职责

- `processor.py`
  - 对外统一入口
- `schemas.py`
  - 统一结果结构
- `types.py`
  - 文件类型和推断逻辑
- `impl/dispatcher.py`
  - 文件类型分发
- `impl/pdf/`
  - PDF 处理和 Docling 适配
- `impl/doc/`
  - DOCX 的 Docling 处理
- `impl/docling_blocks.py`
  - Docling 文档到统一 block 的转换
- `impl/markdown_export.py`
  - block 到 markdown 的导出

## 重命名说明

该模块原名为 `ocr_processor`，但实际职责已经超出 OCR，本次统一改名为 `document_processor`，以突出“文档标准化”而不是单一 OCR 技术细节。
