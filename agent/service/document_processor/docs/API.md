# Document Processor API

This document describes the Python and HTTP contract for
`service.document_processor`。`process(...)` 是唯一公共入口，按类型分流：
PDF 走 MinerU，DOCX 走 `python-docx`，两者返回同一个 `ProcessResult` 形状。

## Python Entry

```python
from service.document_processor.processor import process

pdf_result = process(pdf_file_obj, file_type=None)
docx_result = process(docx_file_obj)
```

`process(...)` is the single public entry. It validates the file-like object,
resolves the source filename, and dispatches by detected type: explicit
`file_type` wins, otherwise the filename suffix decides PDF vs DOCX.

Requirements:

- `file_obj` must expose a callable `read()`.
- If `file_obj` exposes `seek()`, the processor rewinds before and after reading.
- `file_type` may be `"pdf"` / `".pdf"` or `"docx"` / `".docx"`.
- Without `file_type`, the filename suffix (`.pdf` / `.docx`) decides the type.
- If no filename exists, PDF falls back to `document.pdf`; DOCX to `document.docx`.

Failures:

- unreadable object: `InvalidFileObjectError`
- unsupported type: `UnsupportedFileTypeError`
- PDF MinerU failure: `MinerUConversionError`
- DOCX parse failure: `python-docx` raises the underlying package exception.

## HTTP

### Health

```text
GET /healthz
```

```json
{"status": "ok"}
```

### Capabilities

```text
GET /v1/ocr/capabilities
```

```json
{
  "supported_file_types": ["pdf", "docx"],
  "implemented_file_types": ["pdf", "docx"],
  "engine": "mineru-pipeline,python-docx"
}
```

### Process PDF

```text
POST /v1/document-processor/process
POST /v1/ocr/process
```

`multipart/form-data` fields:

- `file`: required PDF upload.
- `file_type`: optional, `pdf` or `.pdf`.

### Process DOCX

```text
POST /v1/document-processor/docx/process
```

`multipart/form-data` fields:

- `file`: required DOCX upload.

Response:

```json
{
  "filename": "sample.pdf",
  "html": "<section ...>...</section>",
  "display_html": "<!doctype html>...",
  "semantic_document": {
    "sections": [],
    "blocks": [],
    "inlines": []
  }
}
```

Fields:

- `filename`: source basename, or `document.pdf` / `document.docx`.
- `html`: traceable extraction HTML fragment.
- `display_html`: self-contained HTML document for user review.
- `markdown`: markdown-like text for storage and audit views.
- `md_list`: block text list.
- `blocks`: page-aware evidence blocks using rendered ids.
- `semantic_document`: section/block/inline semantic structure.

`semantic_document` 的生成链路：

```text
MinerU content_list_v2
  -> blocks 保留 block_id/page_no/bbox/kind
  -> 过滤 page_header/page_number
  -> heading 到下一个 section 前的内容聚合成 section.text
  -> block 识别 lead_in/clause/paragraph/list_item/table/signature
  -> inline 切出 clause_body、condition、definition 等短片段
```

DOCX 的生成链路：

```text
python-docx Document
  -> 按 Word body 原始顺序读取 paragraph/table
  -> 仅 Word heading style 生成 section
  -> 无 heading style 时保持 flat paragraph/table blocks
  -> table row 生成 {table_block_id}_tr_NNN 证据 id
  -> blocks[].page_no 固定为 null
```

## HTML Contract

The processor converts MinerU `content_list_v2.json` to HTML and preserves:

- `id`
- `data-element-id`
- `data-page`
- `data-type`
- `data-level`
- `data-bbox`
- table HTML
- table captions and footnotes

HTML fragment 的层级和检索规则：

```text
level=2 title
  -> <section id="{block_id}_section"> wrapper
  -> <h2 id="{block_id}"> heading，可被 read_section 检索
level=3 title
  -> <section id="{block_id}_subsection"> wrapper
  -> <h3 id="{block_id}"> heading，可被 read_section 检索
level>=4 title
  -> <p id="{block_id}" data-type="title" data-level="N">，作为普通 block 检索
paragraph/list/table
  -> 原生 <p>/<ul>/<table>，block id 直接放在该标签上
```

Pages without visible text/table content are omitted from generated HTML.
Image-only blocks and MinerU source image paths are not rendered.

The processor does not perform field extraction and does not merge continued
tables in this version.
