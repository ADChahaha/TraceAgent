# `test_integration.py`

Uses a temporary synthetic PDF file for the file object path while mocking MinerU
execution.

- `test_process_handles_pdf_file_path_via_public_interface`: writes a minimal
  `%PDF` file under `tmp_path`, opens it through the normal filesystem API, and
  verifies that `processor.process(...)` preserves the filename, reads the
  source bytes, calls the MinerU adapter, and maps the mocked content list into
  HTML. This keeps the public file-object path covered without committing real
  document fixtures or requiring model downloads during unit tests.
