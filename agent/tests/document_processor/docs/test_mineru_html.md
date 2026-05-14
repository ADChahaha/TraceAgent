# `test_mineru_html.py`

Tests conversion from MinerU `content_list_v2` pages to traceable extraction HTML,
display HTML, markdown-like text, backend evidence blocks, and semantic
section/block/inline output.

实现步骤：

```text
MinerU pages
  -> 过滤 image/page_number/page_header/page_footer 这类不可用于推理的噪声
  -> title/paragraph/list/table 渲染成 HTML、Markdown 和 blocks
  -> 页面 wrapper 只保留定位属性，不主动插入 `Page N` 可见页码
  -> level=2 的 title 在 HTML 中打开 section，收纳到下一个 h2 前的块
  -> level=3 的 title 在当前 section 中打开 subsection，收纳到下一个 h2/h3 前的块
  -> level>=4 的 title 降级为普通段落 block，不再让工具当成 section heading
  -> list/table 的主 block id 直接落在原生 ul/table 上，后续工具可按该 id 检索
  -> build_semantic_document_from_blocks(...) 可复用缓存的 MinerU blocks
  -> semantic_document 把 heading 后直到下一个 section 的内容收进 section.text
  -> section 内 block 识别 lead_in、clause、paragraph、list_item 等类型
  -> clause block 继承最近的 lead_in 作为 parent_block_id
  -> block 内再按分号和条件短语生成 inline 片段
```

测试覆盖：

- `test_build_html_from_content_list_preserves_ids_metadata_and_tables`：确认 HTML 保留稳定 id、MinerU metadata、bbox、列表项和表格行 id，并且不会暴露 MinerU 图片路径。
- `test_build_display_html_wraps_extraction_html_with_replay_style`：确认展示 HTML 包含抽取 HTML 和 evidence highlight 样式，同时不主动注入 `.page-number` 可见页码。
- `test_build_html_wraps_h2_and_h3_in_section_hierarchy`：确认 `h2` 标题会打开语义 `<section>`，`h3` 标题会打开语义 subsection，`h4` 及以下标题会作为普通 block 留在当前层级。
- `test_build_html_skips_pages_without_visible_content`：确认空页和纯图片页不会进入 HTML。
- `test_build_html_skips_pages_with_only_page_number`：确认纯页码页不会进入 HTML、blocks 或 Markdown。
- `test_build_outputs_skip_page_footer_noise`：确认页脚版本号不会进入 extraction HTML、display HTML、blocks、Markdown 或 semantic_document。
- `test_build_blocks_from_content_list_uses_rendered_ids_for_text_list_and_table_rows`：确认 blocks 和 HTML 复用同一套可追踪 id，表格行也能作为 evidence block。
- `test_build_markdown_from_content_list_keeps_basic_structure`：确认标题和列表能转成基础 Markdown。
- `test_build_semantic_document_groups_sections_blocks_and_inlines`：确认 section 包含标题和正文内容，page header 被过滤，clause 挂到最近 lead-in，inline 能切出条件片段。
- `test_build_semantic_document_from_blocks_reuses_cached_mineru_blocks`：确认已有 `document_processor.json` 里的 blocks 不重跑 MinerU 也能生成相同三层结构。
