# Document Processor Design

`service.document_processor` converts uploaded documents into HTML that is usable
by the extraction agent and by the backend replay view. PDF and DOCX use separate
HTTP routes and separate processor modules because their source structures are
different: PDF goes through MinerU/OCR, while DOCX is parsed from Word's document
structure.

## Scope

The module handles PDF and DOCX. It does not extract task fields, and it does
not support legacy `.doc`.

## Entry

`processor.process(file_obj, file_type=None)` is the single public entry. It
validates the file-like object, resolves the source filename, and dispatches by
detected type (explicit `file_type` wins, otherwise the filename suffix). Both
PDF and DOCX pipelines are reached only through this entry; the document type
is decided once at the boundary.

```text
file_obj
  -> processor.process(file_obj, file_type)
  -> validate_file_obj(...)
  -> resolve_filename(...)
   -> detect_file_type(file_type, filename):
        ├─ pdf  -> _process_pdf(...)
        └─ docx -> _process_docx(file_obj, filename)
```

For PDF, the pipeline is:

```text
file_obj
  -> processor.process(file_obj, file_type)
  -> validate_file_obj(...)
  -> resolve_filename(...)
  -> detect_file_type(...) -> "pdf"
  -> read_source_bytes(...)
  -> mineru_converter.convert_pdf_bytes_to_content_list(...)
  -> mineru_html.build_blocks_from_content_list(...)
  -> mineru_html.build_semantic_document_from_content_list(...)
  -> mineru_html.build_html_from_content_list(...)
  -> mineru_html.build_display_html_from_content_list(...)
  -> mineru_html.build_markdown_from_content_list(...)
  -> ProcessResult(filename, html, display_html, markdown, md_list, blocks, semantic_document, meta_info, warnings)
```

DOCX pipeline:

```text
file_obj
  -> processor.process(file_obj, file_type)
  -> validate_file_obj(...)
  -> resolve_filename(...)
   -> detect_file_type(...) -> "docx"
  -> _process_docx(file_obj, filename)
  -> read_source_bytes(...)
  -> python-docx Document(BytesIO(source_bytes))
  -> iter_block_items(document) 按 Word body 原始顺序遍历 paragraph/table
  -> paragraph style 是 Heading 1/2/3... 时打开或切换 section stack
  -> 普通 paragraph 保留原文顺序，生成 paragraph block
  -> table 保留原文顺序，生成 table block 和 row evidence
  -> 生成 html / display_html / markdown / md_list / blocks / semantic_document
  -> ProcessResult(..., meta_info.engine="python-docx")
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

This is the single module that owns the public entry, the shared entry helpers,
the PDF orchestration, and the DOCX parsing. Nothing else in the package is
reachable from outside except `ProcessResult` (via `schemas.py`).

The shared entry helpers live here so there is no separate `common` module:
- `InvalidFileObjectError`, `UnsupportedFileTypeError`: exceptions.
- `validate_file_obj(file_obj)`: requires callable `read()`.
- `resolve_filename(file_obj, *, fallback)`: uses `filename`, then `name`, then
  `fallback` (default `document.pdf`).
- `normalize_file_type(value)`: lowercase, strip dots.
- `detect_file_type(file_type, filename)`: explicit type wins, else filename
  suffix; returns `"pdf"` or `"docx"` or raises `UnsupportedFileTypeError`.
- `read_source_bytes(file_obj)`: reads bytes and rewinds when possible.

Public contract:
- `process(file_obj, file_type=None)`: validates, resolves filename, and
  dispatches to PDF or DOCX by `detect_file_type(...)`.
- `_process_pdf(file_obj, filename)`: internal PDF branch (reads bytes and
  drives the MinerU pipeline).
- `_process_docx(file_obj, filename)`: internal DOCX branch (reads bytes and
  parses with python-docx).

`processor.py` 的分流逻辑：

```text
调用方传入 file_obj，可选传 file_type
  -> validate_file_obj(...)
  -> resolve_filename（docx 缺省 document.docx，否则 document.pdf）
  -> detect_file_type(file_type, filename)
       ├─ docx -> _process_docx(...)，engine="python-docx"
       └─ pdf  -> _process_pdf(...)，engine="mineru-pipeline"
```

`_process_docx` deliberately does not guess headings from font size, bold text
or manual formatting. Only explicit Word heading styles create sections;
documents without heading styles become a flat ordered set of paragraph/table
blocks under the document root.

DOCX semantic tree construction:

```text
上传的 .docx file_obj
  -> processor.process(...) 已完成 file-like 校验、文件名解析和类型分流
  -> _process_docx(file_obj, filename) 读取 bytes 并复位文件指针
  -> python-docx 打开 Document(BytesIO(bytes))
  -> 按 document.element.body 原始顺序读取 paragraph/table
  -> paragraph 文本为空则跳过
  -> paragraph style.name 匹配 Heading N / 标题 N 时：
       创建 section，section_id 使用 docx_bNNN
       用 heading level 维护 section stack
  -> 非 heading paragraph：
       生成 docx_bNNN paragraph block
       如果当前有 section，挂到最近 section；否则挂到 document root
  -> table：
       生成 docx_bNNN table block
       每个非空 row 生成 docx_bNNN_tr_NNN 行级 evidence
       table 挂到当前 section 或 document root
  -> 返回 ProcessResult
```

DOCX evidence id 只表达文档内顺序，不表达页码或 bbox：

```text
docx_b001
docx_b002
docx_b003_tr_001
```

输出约束：

- `html` 是供 QA agent 建虚拟文档树的 traceable fragment。
- `display_html` 是带基础样式的完整 HTML，前端右侧 review iframe 直接使用。
- `blocks` 的 `block_id` 与 HTML DOM id 一致；table row 的 id 使用
  `{table_block_id}_tr_NNN`。
- `semantic_document.sections` 只来自 Word heading style。
- 没有 heading style 时不做启发式标题识别，所有非空段落都作为
  paragraph block 保留原顺序。
- DOCX 没有稳定 page/bbox，`blocks[].page_no` 固定为 `None`，`meta_info`
  标记 `engine=python-docx`。

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
- `build_semantic_document_from_content_list(...)`: section/block/inline
  semantic structure for section-level context and fine evidence highlighting.
- `build_markdown_from_content_list(...)`: markdown-like text for storage and
  audit views. It keeps the rendered block order and separates true headings
  from body-local subheadings.

`semantic_document` 的基础实现思路：

```text
MinerU content_list_v2 pages
  -> 复用 build_blocks_from_content_list(...) 生成稳定 block_id/page_no/bbox/kind
  -> 过滤 page_header/page_number/page_footer 等不适合推理的页眉、页码和页脚版本号噪声
  -> 遇到 heading block 创建新 section
  -> section.text 收入 heading 本身和直到下一个 section 前的所有正文 block
  -> block 按 heading/lead_in/clause/paragraph/list_item/table/signature 标注类型
  -> clause block 挂到最近一个以冒号结尾的 lead_in block
  -> block 内按分号和条件短语生成 inline 片段
  -> 返回 {"sections": [...], "blocks": [...], "inlines": [...]}
```

HTML fragment 的层级输出规则：

```text
MinerU content_list_v2 pages
  -> 逐页过滤不可见 block 以及 page_header/page_number/page_footer 文档 chrome
  -> 先把可渲染 block 拉平成带 page_no/block_idx/bbox 特征的 rendered blocks
  -> 识别 `目次` / `Contents` 这类目录页标题，并把同页后续条目标为目录条目
  -> 识别正文小标题样式（`1）` / `【...】` / `(..)` 括号编号 / `<<..>>` / 单字母标号 / 短标题）
  -> 其余 title 直接信任 MinerU 的 content.level 生成对应 heading（不再做层次聚类）
  -> 目录条目和正文小标题没有 heading_level，只作为普通正文段落
  -> 页面 wrapper 只保留 `section.page` 和 `data-page` 定位属性，不主动插入 `Page N` 可见页码
  -> HTML 和 Markdown 复用同一份 rendered block 分类结果
  -> 真 heading 才输出 h1/h2/h3 并参与 section/subsection 包裹
  -> 正文小标题输出为普通 `<p>...</p>`，不参与 outline_tree
  -> 目录页条目保留可见文本，但不打开 section/subsection
  -> level=2 title 打开 <section id="{block_id}_section">，标题本身保留为 <h2 id="{block_id}">
  -> level=3 title 打开 <section id="{block_id}_subsection">，标题本身保留为 <h3 id="{block_id}">
  -> level>=4 title 不再作为章节层级，降级为 <p id="{block_id}" data-type="title" data-level="N">
  -> paragraph/list/table 分别输出为原生 <p>/<ul>/<table> block，block id 直接放在该标签上
  -> list item 和 table row 继续输出稳定子证据 id
```

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
agent can actually use. In generated HTML, level-2 titles define section
wrappers, level-3 titles define subsection wrappers, and level-4 or deeper
titles stay at ordinary block level so downstream tools do not treat them as
additional section scopes. The converter no longer runs layout clustering to
infer chapter levels; only `目次`-page entries and body subheadings are demoted.

Markdown 输出的层级规则：

```text
MinerU content_list_v2 pages
  -> 过滤 page_header/page_number/page_footer/image 等不进入推理正文的 block
  -> 按原始页序和页内顺序收集 title/paragraph/list/table
  -> 先识别目录页，目录条目不参与 Markdown heading 或 HTML section
  -> title 的 heading_level 与 HTML 共用同一份分类结果（目次条目 / 正文小标题降级）
  -> 其余 title 直接信任 MinerU content.level 生成对应 Markdown heading
  -> 以 `1）`、`【...】`、`<<..>>`、`(..)` 括号编号、单字母标号等样式识别正文小标题
  -> 这些正文小标题不再当成 Markdown heading，统一降级为普通正文行
  -> 真标题继续按 heading 输出，保持原文顺序和正文内容紧跟其后
  -> paragraph/list/table 保持在原文顺序中，跟随对应标题输出
```

标题层级不再做聚类/特征推断，只做轻量过滤：MinerU 在部分 PDF 里会把 `1．`
大章、`1）` 小节和 `【注意事項】` 都标成同一层；Markdown 会保留原文顺序，
但只把明显属于正文小标题的样式（`1）`、`【...】`、括号编号等）从 heading
降级，避免把它们和真正的章节标题混在一起。不再根据版面 height/width/
聚类选 h2 频带，也不删除日期/締切提示行或 ASCII 点后无空格的紧凑编号标题。

## Table Handling

Continued-table merging is disabled. The output keeps MinerU table cells and row
content, but normalizes the first `<table>` id to the document block id and
injects deterministic `<tr>` ids so table lookup tools can address the table and
rows directly.
