# Document Processor Design

`service.document_processor` converts PDF file objects into HTML that is usable
by the extraction agent and by the review UI.

## Scope

The module only handles PDF. It does not extract task fields, route human review,
or provide multiple OCR engines.

## Pipeline

```text
file_obj
  -> processor.process(file_obj, file_type)
  -> validate_file_obj(...)
  -> resolve_filename(...)
  -> validate_pdf_type(...)
  -> read_source_bytes(...)
  -> mineru_converter.convert_pdf_bytes_to_content_list(...)
  -> mineru_html.build_blocks_from_content_list(...)
  -> mineru_html.build_html_from_content_list(...)
  -> mineru_html.build_display_html_from_content_list(...)
  -> mineru_html.build_markdown_from_content_list(...)
  -> ProcessResult(filename, html, display_html, markdown, md_list, blocks, meta_info, warnings)
```

## Files

```text
service/document_processor/
├── __init__.py
├── processor.py
├── schemas.py
├── mineru_converter.py
├── mineru_html.py
├── README.md
└── docs/
    ├── API.md
    ├── DESIGN.md
    └── DEVLOG.md
```

## `processor.py`

Owns public input validation and orchestration.

- `process(file_obj, file_type=None)`: public entry point.
- `validate_file_obj(file_obj)`: requires callable `read()`.
- `resolve_filename(file_obj)`: uses `filename`, then `name`, then `document.pdf`.
- `validate_pdf_type(...)`: accepts only PDF.
- `read_source_bytes(file_obj)`: reads bytes and rewinds when possible.

## `mineru_converter.py`

Owns MinerU execution.

- `convert_pdf_bytes_to_content_list(...)`: writes bytes to a temporary PDF,
  runs `mineru -b pipeline -m auto -l <DOCUMENT_PROCESSOR_MINERU_LANG> -f false -t true`, and loads
  `*_content_list_v2.json`.
- `resolve_mineru_executable()`: uses `MINERU_BIN` or `PATH`.
- `resolve_mineru_lang()`: uses `DOCUMENT_PROCESSOR_MINERU_LANG`, defaulting to
  `japan`.
- `build_mineru_env()`: sets conservative runtime defaults.
- `find_content_list_v2(...)`: locates the MinerU artifact.

MinerU errors are fail-fast. There is no fallback engine.

## `mineru_html.py`

Owns conversion from MinerU pages to HTML.

- `build_html_from_content_list(...)`: extraction HTML fragment.
- `build_display_html_from_content_list(...)`: full HTML document with CSS.
- `build_blocks_from_content_list(...)`: backend evidence blocks using the same
  rendered ids as HTML.
- `build_markdown_from_content_list(...)`: markdown-like text for storage and
  audit views.

IDs are deterministic from page and block position:

```text
page_001
p001_b000
p001_b001_item_000
```

The converter preserves page, type, title level, bbox, table HTML, captions,
and footnotes for visible text/table content. `blocks` reuse the rendered HTML
ids for paragraphs, headings, list items and table rows so backend can recover
evidence text by id. Empty pages, image-only blocks, and source image debug
paths are filtered out so replay HTML only shows content that the extraction
agent can actually use.

## Table Handling

Continued-table merging is disabled. The output keeps MinerU table HTML as-is.
