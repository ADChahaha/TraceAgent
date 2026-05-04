# `test_mineru_html.py`

Tests conversion from MinerU `content_list_v2` pages to traceable extraction HTML,
display HTML, markdown-like text, and backend evidence blocks. The table test
also verifies that rendered table rows and stored row blocks use the same ids so
agent actions can be replayed and route-policy refs can be resolved. The HTML
tests also cover replay cleanup: image-only/empty pages are omitted, and MinerU
source image paths are not rendered as visible `source:` text.
