# `test_document_processor_route.py`

This document corresponds to `tests/routes/test_document_processor_route.py`.

## Flow

```text
HTTP request
  -> FastAPI document processor router
  -> capabilities returns PDF + DOCX engine declaration
  -> multipart file + file_type upload
  -> UploadFileProxy exposes a file-like object
  -> /v1/document-processor/process      调 processor.process(file_obj, file_type)（pdf/docx 都由 file_type 判定）
  -> ProcessResult(filename, html)
  -> JSON response
```

## Tests

`test_document_processor_capabilities_route_reports_pdf_and_docx_processors`

- Verifies `/v1/ocr/capabilities`.
- Verifies supported types are `pdf` and `docx`.
- Verifies engine declaration includes MinerU and python-docx.

`test_document_processor_route_uses_public_processor_exception_contract`

- Verifies the route does not import old implementation packages.
- Verifies the route depends on the public processor exception contract.

`test_document_processor_process_route_calls_business_processor`

- Mocks business `process(...)`.
- Verifies upload and `file_type` forwarding.
- Verifies JSON response shape, including structured blocks and semantic document output used later for evidence lookup.

`test_document_processor_docx_processes_via_general_route`

- Mocks unified `process(...)` (forwarding `file_type="docx"`).
- Verifies DOCX upload goes through `/v1/document-processor/process` with `file_type="docx"`, forwards it as a file-like object to the unified entry, and returns `ProcessResult(filename, html)`.

`test_document_processor_dedicated_docx_route_is_removed`

- Verifies the dedicated `/v1/document-processor/docx/process` endpoint no longer exists (returns 404), since PDF/DOCX share the single general `/process` entry and are dispatched by `file_type`.

`test_document_processor_legacy_ocr_process_route_is_removed`

- Mocks business `process(...)`.
- Verifies the legacy `/v1/ocr/process` endpoint no longer exists (returns 404); the only document-processing route is `POST /v1/document-processor/process`.
