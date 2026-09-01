# `test_mineru_html.py`

Tests conversion from MinerU `content_list_v2` pages to traceable extraction HTML,
display HTML, markdown-like text, backend evidence blocks, and semantic
section/block/inline output.

实现步骤：

```text
MinerU pages
  -> 过滤 image/page_number/page_header/page_footer 这类不可用于推理的噪声
  -> title/paragraph/list/table 渲染成 HTML、Markdown 和 blocks
  -> 保留两类轻量过滤：`目次` 页目录条目不进真章节；正文小标题（`1）`/`【..】`/
     `(..)` 括号编号/`<<>>`/单字母标号等）降级为普通正文行
  -> 其余 title 直接信任 MinerU 的 content.level 生成对应 heading（不再做层次聚类）
  -> 页面 wrapper 只保留定位属性，不主动插入 `Page N` 可见页码
  -> level=2 title 打开 section；level=3 title 在当前 section 打开 subsection
  -> level>=4 的 title 降级为普通 paragraph block，不再让工具当成 section heading
  -> list/table 的主 block id 直接落在原生 ul/table 上，后续工具可按该 id 检索
  -> Markdown 输出保留 rendered block 原文顺序，不写入调试注释
  -> Markdown 标题按同上的 heading_level 规则生成，正文字体小标题降级为普通正文行
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
- `test_build_html_renders_body_subheadings_without_section_nodes`：确认正文里的 `1）` 这类小标题只渲染为普通段落，不会生成 heading 或 section 节点；而 `3．出願手続` 这类真标题仍生成 section。
- `test_build_html_keeps_table_of_contents_entries_out_of_outline_headings`：确认 `目次` 页里的目录项只作为可见文本保留，不会生成 section；同名真实章节在正文页仍会生成 section。
- `test_build_markdown_keeps_deadline_title_as_heading`：确认带日期和时间的提出期限提示行即使被 MinerU 标成 `title level=2`，现在按 level 直接输出 Markdown heading 和 HTML section（不再做日期启发式降级）。
- `test_build_markdown_keeps_compact_numbered_title_as_heading`：确认 `2.日程` 这类紧凑编号 title 按 level 输出为 heading；不再用特征/聚类降级。
- `test_build_html_skips_pages_without_visible_content`：确认空页和纯图片页不会进入 HTML。
- `test_build_html_skips_pages_with_only_page_number`：确认纯页码页不会进入 HTML、blocks 或 Markdown。
- `test_build_outputs_skip_page_footer_noise`：确认页脚版本号不会进入 extraction HTML、display HTML、blocks、Markdown 或 semantic_document。
- `test_build_blocks_from_content_list_uses_rendered_ids_for_text_list_and_table_rows`：确认 blocks 和 HTML 复用同一套可追踪 id，表格行也能作为 evidence block。
- `test_build_markdown_from_content_list_keeps_basic_structure`：确认标题和列表能转成基础 Markdown，并且输出不包含调试注释。
- `test_build_markdown_from_content_list_embeds_clustered_block_structure`：确认 Markdown 会按原文顺序输出每个 block，并保持真标题的 heading 层级。
- `test_build_markdown_from_content_list_separates_true_titles_from_body_subheadings`：确认正文里的 `1）`、`【...】` 这类小标题会被降级为普通正文行，而真正的章节标题仍然保持 Markdown heading。
- `test_build_markdown_from_content_list_promotes_numbered_paragraph_body_items`：确认分隔的段落保持普通正文行，而 `3．「エッセイ」...` 这类标题按 level 输出为 heading。
- `test_build_semantic_document_groups_sections_blocks_and_inlines`：确认 section 包含标题和正文内容，page header 被过滤，clause 挂到最近 lead-in，inline 能切出条件片段。
- `test_extract_inline_id_is_stable_from_normalized_text`：确认 inline id 由归一化文本哈希得到，稳定且与空格无关。
- `test_build_semantic_document_from_blocks_reuses_cached_mineru_blocks`：确认已有 `document_processor.json` 里的 blocks 不重跑 MinerU 也能生成相同三层结构。
