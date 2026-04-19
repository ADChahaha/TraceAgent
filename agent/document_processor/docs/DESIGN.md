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
- `DOCX -> python-docx -> markdown + blocks` 的真实处理链路

后续再补的部分是：

- `pdf` 的真实解析算法
- block 标准化细节
- markdown 导出细节

## DOCX 实现

当前 `DOCX` 已经落地为单一路径实现，入口在 `impl/docx/processor.py`。

实现步骤：

```text
调用方传入 docx file_obj
  -> `document_processor.process(...)` 先校验 read() 并解析出 FileType.DOCX
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
  - 预留给 PDF 真实处理器实现
- `impl/docx/`
  - `processor.py`：基于 `python-docx` 的 DOCX 处理器
  - 只负责 `DOCX` 的二进制读取、段落/表格遍历、markdown 导出和 block 归一化
- `impl/docling_blocks.py`
  - 预留给 block 标准化转换
- `impl/markdown_export.py`
  - 预留给 markdown 导出

## 重命名说明

该模块原名为 `ocr_processor`，但实际职责已经超出 OCR，本次统一改名为 `document_processor`，以突出“文档标准化”而不是单一 OCR 技术细节。
