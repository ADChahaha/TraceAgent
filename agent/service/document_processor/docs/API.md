# Document Processor API

本模块提供内部 Python 解析接口。对外 HTTP 由文档资源 route 统一串联解析与索引构建，返回资源路径与 HTML。`process(...)` 是唯一公共入口，按类型分流：
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

## HTTP 边界

独立解析 HTTP 入口已合并到 `POST /v1/document-resources`，接收多个 files，完成解析、文档树和 embedding 后返回 resource_path 与 documents。请求示例和错误码见 [agent API](../../../docs/API.md)。

本模块仍只返回 ProcessResult(filename, html)，不承担资源目录或索引生命周期。

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
