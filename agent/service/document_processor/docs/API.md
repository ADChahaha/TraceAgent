# Document Processor API

这份文档面向调用方，说明 `service.document_processor` 的 Python 入口、HTTP 入口、请求字段、返回结构和边界。它只描述对外稳定契约；内部 PDF / DOCX 解析实现见 [`DESIGN.md`](DESIGN.md)。

## 基本链路

`service.document_processor` 接收原始 PDF / DOCX 文件对象，输出统一的 Markdown 和 blocks。它不做字段抽取，也不负责给 blocks 生成业务稳定 `block_id`；如果后续要调用 `service.file_extraction_agent`，应由 backend 或 session 聚合层给每个 block 补稳定唯一 id。

```text
调用方传入 file_obj，可选传 file_type
  -> service.document_processor.processor.process(...)
  -> 校验 file_obj 至少提供可调用 read()
  -> 优先使用显式 file_type，否则从 file_obj.filename / file_obj.name 推断后缀
  -> 归一化成 FileType.PDF 或 FileType.DOCX
  -> InternalProcessorInterface 按 FileType 选择 PdfProcessor 或 DocxProcessor
  -> 具体处理器读取二进制并生成 markdown、md_list、blocks、meta_info
  -> ProcessResult
```

## Python 入口

入口函数：

```python
from service.document_processor.processor import process

result = process(file_obj, file_type=None)
```

调用要求：

- `file_obj` 必须至少有可调用的 `read()`。
- 如果 `file_obj` 有 `seek()`，处理器会在读取前后尝试回到文件开头。
- `file_type` 可传 `"pdf"`、`"docx"`、`".pdf"`、`".docx"` 或 `FileType` 枚举。
- 不传 `file_type` 时，会从 `file_obj.filename` 或 `file_obj.name` 的后缀推断。

最小示例：

```python
from pathlib import Path

from service.document_processor.processor import process


with Path("sample.pdf").open("rb") as file_obj:
    result = process(file_obj, file_type="pdf")

print(result.file_type)
print(result.markdown)
print(len(result.blocks))
```

失败语义：

- `file_obj` 没有可调用 `read()`：抛 `InvalidFileObjectError`。
- 无法推断类型，或类型不是 `pdf/docx`：抛 `UnsupportedFileTypeError`。
- 目标类型没有注册处理器：抛 `NotImplementedError`。
- PDF / DOCX 底层解析失败时，保留底层异常向上抛出。

## HTTP 入口

路由由 `routes.document_processor` 提供。

### 健康检查

```text
GET /healthz
```

响应：

```json
{
  "status": "ok"
}
```

### 能力查询

```text
GET /v1/ocr/capabilities
```

响应示例：

```json
{
  "supported_file_types": ["pdf", "docx"],
  "implemented_file_types": ["pdf", "docx"],
  "docling_artifacts_path": "/path/to/service/document_processor/impl/pdf/models/docling",
  "docling_artifacts_available": true
}
```

说明：

- `supported_file_types` 来自 `FileType` 枚举。
- `implemented_file_types` 表示当前已注册真实处理器的类型。
- `docling_artifacts_path` 和 `docling_artifacts_available` 只描述 PDF docling 模型目录状态。

### 文档处理

规范路径：

```text
POST /v1/document-processor/process
```

兼容旧路径：

```text
POST /v1/ocr/process
```

请求类型是 `multipart/form-data`：

- `file`：必填上传文件。
- `file_type`：可选，显式文件类型；为空时从上传文件名推断。

`curl` 示例：

```bash
curl -X POST "http://localhost:8000/v1/document-processor/process" \
  -F "file=@sample.pdf" \
  -F "file_type=pdf"
```

HTTP 错误语义：

- 缺少 `file` 或表单形状不符合 FastAPI 要求：FastAPI 返回 `422`。
- 不支持或无法推断 `file_type`：route 层返回 `422`。
- 上传对象不满足最小 file-like 契约：route 层返回 `422`。
- 底层解析器运行时失败：当前不在 route 层吞掉，会按服务默认异常处理返回错误。

## 返回结构

Python 入口返回 `service.document_processor.schemas.ProcessResult`，HTTP 入口返回同形状 JSON：

```json
{
  "file_type": "pdf",
  "filename": "sample.pdf",
  "md_list": ["# 标题\n\n正文"],
  "markdown": "# 标题\n\n正文",
  "blocks": [
    {
      "text": "正文",
      "page_no": 1,
      "bbox": {
        "x0": 10.0,
        "y0": 20.0,
        "x1": 200.0,
        "y1": 40.0
      },
      "kind": "text",
      "meta_info": {}
    }
  ],
  "meta_info": {
    "block_count": 1,
    "page_count": 1
  },
  "warnings": []
}
```

字段说明：

- `file_type`：实际处理类型，当前为 `pdf` 或 `docx`。
- `filename`：从 `filename/name` 提取的文件名；缺省时 PDF 回退为 `document.pdf`，DOCX 回退为 `document.docx`。
- `markdown`：整篇文档的 Markdown 文本。
- `md_list`：当前通常是包含整篇 Markdown 的单元素列表；无文本时为空。
- `blocks`：后续抽取可消费的标准化内容块。
- `meta_info`：处理器级统计或补充信息。
- `warnings`：非致命 warning；当前大多数底层解析错误会直接抛异常，不会写入 warning 后继续。

## block 结构

`blocks[]` 的结构是：

```text
ContentBlock
  -> text: str
  -> page_no: int | None
  -> bbox: BoundingBox | None
  -> kind: str
  -> meta_info: dict
```

`kind` 当前主要取值：

- `text`：普通正文。
- `section_header`：标题或章节标题。
- `table`：表格行或表格节点。

`bbox` 当前主要来自 PDF provenance；DOCX 通常没有页面坐标。

注意：`service.document_processor` 不生成 `block_id`。如果结果要进入 `service.file_extraction_agent`，调用方需要在 session 聚合阶段把每个 `ContentBlock` 转成 `service.file_extraction_agent.schemas.NormalizedBlock`，并补齐稳定唯一的 `block_id`。

## PDF 行为

PDF 固定走 `docling + RapidOCR`：

```text
pdf file_obj
  -> PdfProcessor 读取二进制
  -> 包装成 docling DocumentStream
  -> DocumentConverter.convert(...)
  -> export_to_markdown()
  -> iterate_items() 生成 ContentBlock[]
  -> ProcessResult(file_type="pdf")
```

如果调用方没有显式配置模型目录，运行时会把相关下载和缓存默认收口到 `service/document_processor/impl/pdf/models/` 下：

- `DOCLING_CACHE_DIR`
- `RAPIDOCR_MODEL_ROOT`
- `HF_HOME`

可在启动服务前通过环境变量覆盖这些目录。

## DOCX 行为

DOCX 固定走 `python-docx`：

```text
docx file_obj
  -> DocxProcessor 读取二进制
  -> Document(BytesIO(...))
  -> 按 body 顺序遍历 paragraph / table
  -> paragraph 转正文或标题 markdown
  -> table 转简单 markdown table 和 table blocks
  -> ProcessResult(file_type="docx")
```

DOCX 路径不依赖 LibreOffice 或桌面应用。

## 不支持的输入

- 不支持 `.doc`。
- 不支持路径字符串直接作为 `file_obj`；调用方应自己打开文件对象。
- 不做字段抽取。
- 不负责生成进入 `service.file_extraction_agent` 所需的 `block_id`。
