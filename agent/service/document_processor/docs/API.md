# Document Processor API

This document describes the Python and HTTP contract for
`service.document_processor`.

## Python Entry

```python
from service.document_processor.processor import process

result = process(file_obj, file_type=None)
```

Requirements:

- `file_obj` must expose a callable `read()`.
- If `file_obj` exposes `seek()`, the processor rewinds before and after reading.
- `file_type` may be `"pdf"` or `".pdf"`.
- Without `file_type`, the filename suffix must be `.pdf`.
- If no filename exists, `document.pdf` is used.

Failures:

- unreadable object: `InvalidFileObjectError`
- unsupported type: `UnsupportedFileTypeError`
- MinerU failure: `MinerUConversionError`

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
  "supported_file_types": ["pdf"],
  "implemented_file_types": ["pdf"],
  "engine": "mineru-pipeline"
}
```

### Process

```text
POST /v1/document-processor/process
POST /v1/ocr/process
```

`multipart/form-data` fields:

- `file`: required PDF upload.
- `file_type`: optional, `pdf` or `.pdf`.

Response:

```json
{
  "filename": "sample.pdf",
  "html": "<section ...>...</section>",
  "display_html": "<!doctype html>..."
}
```

Fields:

- `filename`: source basename, or `document.pdf`.
- `html`: traceable extraction HTML fragment.
- `display_html`: self-contained HTML document for user review.

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

The processor does not perform field extraction and does not merge continued
tables in this version.
