# `test_integration.py`

Uses temporary synthetic PDF / DOCX files for the file object path while mocking
MinerU execution.

- `test_process_handles_pdf_file_path_via_public_interface`: writes a minimal
  `%PDF` file under `tmp_path`, opens it through the normal filesystem API, and
  verifies that `processor.process(...)` preserves the filename, reads the
  source bytes, calls the MinerU adapter, and maps the mocked content list into
  HTML. This keeps the public file-object path covered without committing real
  document fixtures or requiring model downloads during unit tests.
- `test_process_routes_docx_file_path_via_public_interface`: writes a real
  `.docx` (built in memory with python-docx) under `tmp_path`, opens it through
  the filesystem API, and verifies that `process(...)` routes it to the DOCX
  branch, preserving the filename and producing python-docx engine metadata
  with traceable HTML.
