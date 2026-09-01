# Document Processor

`service.document_processor` receives PDF or DOCX file objects and returns
traceable HTML for extraction plus display HTML for inspection. PDF runs MinerU;
DOCX is parsed from Word structure with `python-docx`.

## Supported Input

- Supported: `pdf`, `docx`
- Unsupported: `doc`, path strings

Callers pass an opened binary file object, not a filesystem path.

## Usage

```python
from service.document_processor.processor import process

pdf_result = process(pdf_file_obj, file_type=None)
docx_result = process(docx_file_obj)

print(pdf_result.filename)
print(pdf_result.html)
print(pdf_result.display_html)
```

HTTP endpoints:

- `POST /v1/document-processor/process`
- legacy alias: `POST /v1/ocr/process`
- `POST /v1/document-processor/docx/process`

## Pipeline

```text
调用方传入 PDF / DOCX file_obj，可选传 file_type
  -> validate file object
  -> detect_file_type(file_type, filename)  显式类型优先，否则看后缀
       ├─ pdf  -> MinerU pipeline CLI
       └─ docx -> python-docx Document(BytesIO(...))
  -> traceable extraction HTML + self-contained display HTML
  -> markdown, md_list, backend evidence blocks, semantic_document, meta_info, warnings
  -> ProcessResult(filename, html, display_html, markdown, md_list, blocks, semantic_document, meta_info, warnings)
```

DOCX 解析细节：

```text
python-docx Document
  -> 按 Word body 原始顺序遍历 paragraph/table
  -> 只用 Word heading style 创建 section
  -> 无 heading style 时保留 flat paragraph/table blocks
```

Source files:

- `processor.py`: 唯一公共入口 `process(...)`，内含类型分流、PDF 编排和 DOCX 解析。
- `mineru_converter.py`: MinerU CLI invocation and `content_list_v2` loading.
- `mineru_html.py`: MinerU content list to HTML conversion.
- `schemas.py`: `ProcessResult`.

`blocks` 使用和 HTML 一致的可追踪 id。PDF 普通 block id 形如
`p001_b000`，列表项形如 `p001_b000_item_000`，表格行形如
`p001_b000_tr_000`。DOCX block id 形如 `docx_b001`，表格行形如
`docx_b003_tr_001`。backend 会再补上自己的 `document_id`，用于
replay/audit 展示和字段证据定位。

`semantic_document` 是 MinerU 后处理出的三层语义结构：

```text
MinerU blocks
  -> 过滤 page_header/page_number
  -> heading 创建 section，section.text 包含标题和本 section 的正文
  -> section 内保留 block，block 记录 clause_marker、parent_block_id 和来源 metadata
  -> block 内生成 inline，用于短证据片段和高亮
```

## Output HTML

The generated HTML keeps MinerU structure metadata:

- page sections: `page_001`, `page_002`, ...
- block ids: `p001_b000`, `p001_b001`, ...
- list item ids: `p002_b001_item_000`, ...
- level-2 section wrappers: `p001_b003_section`, ...
- level-3 subsection wrappers: `p001_b004_subsection`, ...
- `data-element-id`
- `data-page`
- `data-type`
- `data-level` for titles
- `data-bbox` when MinerU provides a bounding box
- MinerU table HTML, captions, and footnotes

HTML 层级按下面规则给后续工具检索：

```text
level=2 title -> section wrapper + h2 heading id
level=3 title -> subsection wrapper + h3 heading id
level>=4 title -> 普通 p block，不再作为 section heading
paragraph/list/table -> 原生 p/ul/table block，block id 直接在该标签上
```

Pages without visible text/table content are skipped. Image-only blocks and
MinerU source image paths are not rendered in `html` or `display_html`.

Continued-table merging is currently disabled. Table cells are kept from MinerU,
while the outer table id is normalized to the block id and rows get deterministic
evidence ids.

## Configuration

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `MINERU_BIN` | first `mineru` on `PATH` | MinerU CLI executable. |
| `DOCUMENT_PROCESSOR_MINERU_LANG` | `japan` | MinerU OCR language code passed to `-l`. Use `ch` for Chinese PDFs. |
| `MINERU_API_MAX_CONCURRENT_REQUESTS` | `1` | Conservative local MinerU API concurrency. |
| `MINERU_PROCESSING_WINDOW_SIZE` | MinerU default | Optional MinerU processing window size. |
