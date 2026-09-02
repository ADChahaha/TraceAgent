# Document Processor

`service.document_processor` receives PDF or DOCX file objects and returns a
single self-contained HTML document (`filename` + `html`) with CSS for display.
PDF runs MinerU; DOCX is parsed from Word structure with `python-docx`.

## Supported Input

- Supported: `pdf`, `docx`
- Unsupported: `doc`, path strings

Callers pass an opened binary file object, not a filesystem path.

## Usage

```python
from service.document_processor.processor import process

pdf_result = process(pdf_file_obj, file_type=None)
docx_result = process(docx_file_obj)

print(pdf_result.filename)
print(pdf_result.html)
```

HTTP endpoints:

- `POST /v1/document-processor/process` (PDF/DOCX, dispatched by `file_type` or filename suffix)

## Pipeline

```text
调用方传入 PDF / DOCX file_obj，可选传 file_type
  -> validate file object
  -> detect_file_type(file_type, filename)  显式类型优先，否则看后缀
       ├─ pdf  -> MinerU pipeline CLI
       └─ docx -> python-docx Document(BytesIO(...))
  -> 生成带 CSS 的完整 HTML 文档（含 h1-h6 / p / ul / ol / table 结构骨架）
  -> ProcessResult(filename, html)
```

DOCX 解析细节：

```text
python-docx Document
  -> 按 Word body 原始顺序遍历 paragraph/table
  -> 只用 Word heading style 生成 heading block
  -> 无 heading style 时保留 flat paragraph/table blocks
```

Source files:

- `processor.py`: 唯一公共入口 `process(...)`，只做类型分流、字节读取和结果拼接。
- `pdf/converter.py`: MinerU CLI invocation and `content_list_v2` loading.
- `pdf/html.py`: MinerU content list to HTML conversion.
- `pdf/__init__.py`: 组装 `convert_pdf_to_html(...)` 作为 PDF 子包唯一公共函数。
- `docx/docx_processor.py`: python-docx 解析 DOCX 为 HTML。
- `docx/__init__.py`: 暴露 `convert_docx_to_html(...)` 作为 DOCX 子包唯一公共函数。
- `schemas.py`: `ProcessResult`.

`ProcessResult` 只保留 `filename` + `html`。`html` 是带 CSS 的完整文档：
前端 review / iframe 直接渲染，同时保留 h1-h6 / p / ul / ol / table 结构骨架，
供 `file_extraction_agent` 解析建树。不再返回 `display_html` / `markdown` /
`md_list` / `blocks` / `semantic_document` / `meta_info` / `warnings`。

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
MinerU source image paths are not rendered in `html`.

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
