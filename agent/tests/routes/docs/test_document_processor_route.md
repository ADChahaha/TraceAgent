# `test_document_processor_route.py`

This document corresponds to `tests/routes/test_document_processor_route.py`.

## Flow

```text
HTTP request
  -> FastAPI document processor router
  -> capabilities returns PDF-only MinerU engine declaration
  -> multipart file + file_type upload
  -> UploadFileProxy exposes a file-like object
  -> service.document_processor.processor.process(file_obj, file_type)
  -> ProcessResult(filename, html, display_html, markdown, md_list, blocks, semantic_document, meta_info, warnings)
  -> JSON response
```

## Tests

`test_document_processor_capabilities_route_reports_pdf_only_processor`

- Verifies `/v1/ocr/capabilities`.
- Verifies supported type is only `pdf`.
- Verifies engine is `mineru-pipeline`.

`test_document_processor_route_uses_public_processor_exception_contract`

- Verifies the route does not import old implementation packages.
- Verifies the route depends on the public processor exception contract.

`test_document_processor_process_route_calls_business_processor`

- Mocks business `process(...)`.
- Verifies upload and `file_type` forwarding.
- Verifies JSON response shape, including structured blocks and semantic document output used later for evidence lookup.
