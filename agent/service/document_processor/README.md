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
PDF file_obj
  -> validate file object and PDF type
  -> read PDF bytes
  -> MinerU pipeline CLI
  -> content_list_v2.json
  -> traceable extraction HTML
  -> self-contained display HTML
  -> ProcessResult(filename, html, display_html)
```

Source files:

- `processor.py`: input validation and main orchestration.
- `mineru_converter.py`: MinerU CLI invocation and `content_list_v2` loading.
- `mineru_html.py`: MinerU content list to HTML conversion.
- `schemas.py`: `ProcessResult`.

## Output HTML

The generated HTML keeps MinerU structure metadata:

- page sections: `page_001`, `page_002`, ...
- block ids: `p001_b000`, `p001_b001`, ...
- list item ids: `p002_b001_item_000`, ...
- `data-element-id`
- `data-page`
- `data-type`
- `data-level` for titles
- `data-bbox` when MinerU provides a bounding box
- MinerU table HTML, captions, and footnotes

Pages without visible text/table content are skipped. Image-only blocks and
MinerU source image paths are not rendered in `html` or `display_html`.

Continued-table merging is currently disabled. Table structure is kept as
MinerU emits it.

## Configuration

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `MINERU_BIN` | first `mineru` on `PATH` | MinerU CLI executable. |
| `DOCUMENT_PROCESSOR_MINERU_LANG` | `japan` | MinerU OCR language code passed to `-l`. Use `ch` for Chinese PDFs. |
| `MINERU_API_MAX_CONCURRENT_REQUESTS` | `1` | Conservative local MinerU API concurrency. |
| `MINERU_PROCESSING_WINDOW_SIZE` | MinerU default | Optional MinerU processing window size. |
