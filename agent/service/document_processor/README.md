# Document Processor

`service.document_processor` receives a PDF file object, runs MinerU pipeline,
and returns traceable HTML for extraction plus display HTML for review.

## Supported Input

- Supported: `pdf`
- Unsupported: `docx`, `doc`, path strings

Callers pass an opened binary file object, not a filesystem path.

## Usage

```python
from service.document_processor.processor import process

result = process(file_obj, file_type=None)

print(result.filename)
print(result.html)
print(result.display_html)
```

HTTP endpoints:

- `POST /v1/document-processor/process`
- legacy alias: `POST /v1/ocr/process`

## Pipeline

```text
调用方传入 PDF file_obj，可选传 file_type
  -> validate file object and PDF type
  -> read PDF bytes
  -> MinerU pipeline CLI
  -> content_list_v2.json
  -> traceable extraction HTML
  -> self-contained display HTML
  -> markdown, md_list, backend evidence blocks, semantic_document, meta_info, warnings
  -> ProcessResult(filename, html, display_html, markdown, md_list, blocks, semantic_document, meta_info, warnings)
```

Source files:

- `processor.py`: input validation and main orchestration.
- `mineru_converter.py`: MinerU CLI invocation and `content_list_v2` loading.
- `mineru_html.py`: MinerU content list to HTML conversion.
- `schemas.py`: `ProcessResult`.

`blocks` 使用和 HTML 一致的可追踪 id。普通 block id 形如
`p001_b000`，列表项形如 `p001_b000_item_000`，表格行形如
`p001_b000_tr_000`。backend 会再补上自己的 `document_id`，用于
route policy 证据文本回填和 replay/audit 展示。

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
