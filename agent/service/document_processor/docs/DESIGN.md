# Document Processor Design

`service.document_processor` converts PDF file objects into HTML that is usable
by the extraction agent and by the backend replay view.

## Scope

The module only handles PDF. It does not extract task fields or provide
multiple OCR engines.

## Pipeline

```text
file_obj
  -> processor.process(file_obj, file_type)
  -> validate_file_obj(...)
  -> resolve_filename(...)
  -> validate_pdf_type(...)
  -> read_source_bytes(...)
  -> mineru_converter.convert_pdf_bytes_to_content_list(...)
  -> mineru_html.build_blocks_from_content_list(...)
  -> mineru_html.build_semantic_document_from_content_list(...)
  -> mineru_html.build_html_from_content_list(...)
  -> mineru_html.build_display_html_from_content_list(...)
  -> mineru_html.build_markdown_from_content_list(...)
  -> ProcessResult(filename, html, display_html, markdown, md_list, blocks, semantic_document, meta_info, warnings)
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

Owns public input validation and orchestration.

- `process(file_obj, file_type=None)`: public entry point.
- `validate_file_obj(file_obj)`: requires callable `read()`.
- `resolve_filename(file_obj)`: uses `filename`, then `name`, then `document.pdf`.
- `validate_pdf_type(...)`: accepts only PDF.
- `read_source_bytes(file_obj)`: reads bytes and rewinds when possible.

`processor.py` 的分流逻辑：

```text
调用方传入 file_obj，可选传 file_type
  -> 校验 file-like 和 PDF 类型
  -> 读取 PDF bytes 并复位文件指针
  -> 调用 MinerU pipeline 生成 content_list_v2
  -> meta_info.engine = "mineru-pipeline"
  -> 复用 mineru_html 生成 html/display_html/markdown/blocks/semantic_document
```

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
  -> 从非目录 title 候选里去掉封面标题、正文句子、日期期限行和明显正文小标题
  -> 对剩余 title 候选按归一化 height/width/chars/line_count/x0 做层次聚类，height 权重为 2，不使用 y0
  -> 选出更像主章节的高置信簇作为 h2 heading_level
  -> 目录条目和不在 h2 簇里的 title 没有 heading_level，只作为正文加粗行
  -> 页面 wrapper 只保留 `section.page` 和 `data-page` 定位属性，不主动插入 `Page N` 可见页码
  -> HTML 和 Markdown 复用同一份 rendered block 分类结果
  -> 真 heading 才输出 h1/h2/h3 并参与 section/subsection 包裹
  -> 正文小标题输出为 `<p><strong>...</strong></p>`，不参与 outline_tree
  -> 目录页条目保留可见文本，但不打开 section/subsection
  -> 全局 h2 高度档 title 打开 <section id="{block_id}_section">，标题本身保留为 <h2 id="{block_id}">
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
additional section scopes.

Markdown 输出的层级和聚类规则：

```text
MinerU content_list_v2 pages
  -> 过滤 page_header/page_number/page_footer/image 等不进入推理正文的 block
  -> 按原始页序和页内顺序收集 title/paragraph/list/table
  -> 为每个 block 计算 height、width、chars、line_count、x0、y0
  -> 先识别目录页，目录条目不参与 Markdown heading 或 HTML section
  -> title 不直接照抄 MinerU level；MinerU level 只作为候选过滤特征
  -> 从 title 候选中取 height、width、chars、line_count、x0 做 MinMax 归一化
  -> 将归一化后的 height 乘以 2，强调真实章节标题和正文局部标题的字号差异
  -> 对候选做 AgglomerativeClustering(n_clusters=2, linkage="ward")
  -> 按簇内平均 height、与候选整体中位 x0 的距离和平均字符数选择 h2 章节簇
  -> 不在 h2 簇里的 title 即使 MinerU 标成 level=2，也降级成加粗正文行
  -> 以 `1）`、`【...】`、`<<...>>`、括号编号、单字母标号等样式识别正文里的小标题
  -> `2.日程` 这类 ASCII 点后无空格的紧凑编号 title 按正文小标题处理，避免把条目标题当成大章
  -> 小字号的 `title + 1．/2．/3．` 编号块也会被视为正文小标题，避免把列表内部项目当成大章
  -> 含提出期限/締切、完整日期和时间或“まで”的提示行，即使 MinerU 标成 title，也作为正文提示行
  -> paragraph 如果是短的独立 `1．` / `2．` 编号块，也作为正文小标题候选处理
  -> 这些正文小标题不再当成 Markdown heading，而是降级为独立的加粗行
  -> 真标题继续按 heading 输出，保持原文顺序和正文内容紧跟其后
  -> paragraph/list/table 保持在原文顺序中，跟随对应标题输出
```

标题层级不是直接照抄 MinerU 的 `level`。MinerU 在部分 PDF 里会把 `1．`
大章、`1）` 小节和 `【注意事項】` 都标成同一层；Markdown 会保留原文顺序，
但会把正文里的小标题降级成加粗行，避免把它们和真正的章节标题混在一起。
这样用户查看 Markdown 时能看到更接近人类阅读的标题结构。

## Table Handling

Continued-table merging is disabled. The output keeps MinerU table cells and row
content, but normalizes the first `<table>` id to the document block id and
injects deterministic `<tr>` ids so table lookup tools can address the table and
rows directly.
