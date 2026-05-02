# Document Processor API

这份文档面向调用方，说明 `service.document_processor` 的 Python 入口、HTTP 入口、请求字段、返回结构和失败语义。内部实现链路见 [`DESIGN.md`](DESIGN.md)。

## 基本链路

`service.document_processor` 接收 PDF 文件对象，使用 docling 转成抽取友好的语义 HTML fragment。它不做字段抽取，不生成 blocks，也不负责给下游抽取链路生成 `document_id` 或 `block_id`。

```text
调用方传入 file_obj，可选传 file_type
  -> service.document_processor.processor.process(...)
  -> 校验 file_obj 至少提供可调用 read()
  -> 从 filename/name 解析文件名，没有则使用 document.pdf
  -> 校验显式 file_type 或文件名后缀必须是 PDF
  -> 读取 PDF bytes
  -> docling DocumentConverter.convert(...)
  -> document.export_to_html(labels=...)
  -> clean_semantic_html(raw_html)
  -> ProcessResult(filename, html)
```

## Python 入口

```python
from service.document_processor.processor import process

result = process(file_obj, file_type=None)
```

调用要求：

- `file_obj` 必须至少有可调用的 `read()`。
- 如果 `file_obj` 有 `seek()`，处理器会在读取前后尝试回到文件开头。
- `file_type` 可传 `"pdf"`、`".pdf"` 或不同大小写形式。
- 不传 `file_type` 时，会从 `file_obj.filename` 或 `file_obj.name` 的后缀判断是否为 PDF。
- 如果文件对象没有文件名，处理器使用默认文件名 `document.pdf`。

最小示例：

```python
from pathlib import Path

from service.document_processor.processor import process


with Path("sample.pdf").open("rb") as file_obj:
    result = process(file_obj)

print(result.filename)
print(result.html)
```

失败语义：

- `file_obj` 没有可调用 `read()`：抛 `InvalidFileObjectError`。
- 显式 `file_type` 不是 PDF，或文件名后缀不是 PDF：抛 `UnsupportedFileTypeError`。
- docling 解析或 HTML 导出失败：保留底层异常向上抛出。

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
  "supported_file_types": ["pdf"],
  "implemented_file_types": ["pdf"],
  "docling_artifacts_path": "/path/to/service/document_processor/models/docling",
  "docling_artifacts_available": true
}
```

说明：

- `supported_file_types` 和 `implemented_file_types` 当前都固定为 `["pdf"]`。
- `docling_artifacts_path` 和 `docling_artifacts_available` 描述 docling 默认缓存目录状态。

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
- `file_type`：可选，传 `pdf` 或 `.pdf`；为空时从上传文件名推断。

`curl` 示例：

```bash
curl -X POST "http://localhost:8000/v1/document-processor/process" \
  -F "file=@sample.pdf" \
  -F "file_type=pdf"
```

HTTP 错误语义：

- 缺少 `file` 或表单形状不符合 FastAPI 要求：FastAPI 返回 `422`。
- 不支持或无法确认 PDF 类型：route 层返回 `422`。
- 上传对象不满足最小 file-like 契约：route 层返回 `422`。
- docling 运行时失败：当前不在 route 层吞掉，会按服务默认异常处理返回错误。

## 返回结构

Python 入口返回 `service.document_processor.schemas.ProcessResult`，HTTP 入口返回同形状 JSON：

```json
{
  "filename": "sample.pdf",
  "html": "<p id=\"dp-p-1\">...</p>"
}
```

字段说明：

- `filename`：从 `filename/name` 提取的文件名；缺省时回退为 `document.pdf`。
- `html`：清理后的语义 HTML fragment。

docling 导出阶段只保留抽取需要的文档 label：

- `TITLE`
- `SECTION_HEADER`
- `TEXT`
- `PARAGRAPH`
- `LIST_ITEM`
- `TABLE`
- `CAPTION`

后处理只清理 HTML 形态：删除 `html/head/body/style/script/meta` 页面壳、CSS、脚本和 `class/style/data-*` 等装饰属性；保留 `id`、`rowspan`、`colspan`。缺少 `id` 的块级节点会被补成 `dp-p-1`、`dp-table-1`、`dp-tr-1` 这类稳定定位 id。表格单元格 `td/th` 不自动补 id，表格证据默认定位到 `tr` 行。

当前不会在 HTML 中输出 `data-dp-type` 或 docling label。原因是 docling 的 `export_to_html(...)` 只把 `labels` 作为导出过滤条件，不会把每个元素的 `DocItemLabel` 原生写入 HTML 属性；本模块也不从标签名反推语义类型。

表格行列数量以 docling 识别结果为准。调用方判断列数时应先按 `rowspan/colspan` 展开表格，再比较实际列宽；不要只按某一行的 `th/td` 个数判断异常。若展开后仍不一致，通常说明 PDF 表格识别阶段存在偏差，而不是 HTML 清理阶段删除了单元格。

## 不支持的输入

- 不支持 `docx`。
- 不支持 `doc`。
- 不支持路径字符串直接作为 `file_obj`。
- 不返回 `markdown`、`md_list`、`blocks`、`meta_info` 或 `warnings`。
