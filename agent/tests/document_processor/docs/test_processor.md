# `test_processor.py`

Tests the public `service.document_processor.processor.process(...)` entry point.

The tests mock MinerU output at `convert_pdf_bytes_to_content_list(...)`, then
assert PDF validation, filename handling, byte reading, generated HTML,
display HTML, markdown, md_list, backend blocks, semantic document output, and
processor metadata.
