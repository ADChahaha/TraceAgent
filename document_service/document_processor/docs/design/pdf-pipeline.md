# PDF MinerU 管线与 HTML 构建规则

本页属 [Document Processor 设计](../DESIGN.md)，说明 `pdf/` 子包的 MinerU 调用、HTML 层级过滤、确定性 ID 与表格处理。

## `pdf/` 入口与 `pdf/converter.py`

`pdf/__init__.py` 对外暴露单一函数 `convert_pdf_to_html(source_bytes, filename)`，串联 `converter` 与 `html` 两步。

`pdf/converter.py` 负责 MinerU 执行（错误 fail-fast，无回退引擎）：

- `convert_pdf_bytes_to_content_list(...)`：将 bytes 写入临时 PDF，执行 `mineru -b pipeline -m auto -l <DOCUMENT_PROCESSOR_MINERU_LANG> -f false -t true`，加载产物 `*_content_list_v2.json`。
- `resolve_mineru_executable()`：优先取 `MINERU_BIN`，否则查找 `PATH`。
- `resolve_mineru_lang()`：读取 `DOCUMENT_PROCESSOR_MINERU_LANG`，默认 `japan`。
- `build_mineru_env()`：设置保守运行时默认环境变量；`find_content_list_v2(...)` 定位 JSON 产物。

## `pdf/html.py` 层级输出规则

- `build_html_from_content_list(...)` 输出带 CSS 壳（`<style>` 含 `dp-evidence-highlight` 等）的完整 HTML 文档，保留 `h1-h6`/`p`/`ul`/`ol`/`table` 骨架及块级 `id`/`data-page`/`data-bbox`。
- 不再生成 `build_display_html_from_content_list`、`build_blocks_from_content_list`、`build_markdown_from_content_list` 或 `semantic_document`；引证粒度收敛到块级（paragraph/list/table）。

```text
MinerU content_list_v2 pages
  -> 过滤不可见块、纯图块、空页、源图调试路径及 page_header/page_number/page_footer
  -> 拉平为带 page_no / block_idx / bbox 的 rendered blocks
  -> 识别"目次"/"Contents"目录页标题并将同页条目降为普通段落（不开 section）
  -> 仅将正文小标题样式（"1）" / "【...】" / "(..)" / "<<..>>" / 单字母标号 / 短标题）降为 <p>
  -> 其余 title 直接信任 MinerU content.level（不再做版面高度/宽度聚类或删日期提示行）
  -> level=2 打开 <section id="{block_id}_section"> 与 <h2 id="{block_id}">
  -> level=3 打开 <section id="{block_id}_subsection"> 与 <h3 id="{block_id}">
  -> level>=4 降级为 <p id="{block_id}" data-type="title" data-level="N">
  -> paragraph/list/table 输出原生 <p>/<ul>/<table>，list item 与 table row 保留稳定子证据 id
```

- 页面 wrapper 只保留 `section.page` 与 `data-page`，不插入可见 `Page N` 文本。
- 保留可见文本与表格的 `page`、`type`、`title level`、`bbox`、表格 HTML、caption 与 footnote；HTML 与 Markdown 复用同一份 rendered block 分类结果。

## 确定性 ID 与表格处理

- ID 由页码与块位置决定：`page_001`、`p001_b000`、`p001_b001_item_000`。
- 跨页续表合并已禁用；输出保留 MinerU 单元格和行内容，并将首个 `<table>` 的 `id` 归一化为文档块 ID，同时为每行 `<tr>` 注入确定性 ID，供下游直接定位表与行。
