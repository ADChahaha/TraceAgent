# `test_mineru_html.py`

Tests conversion from MinerU `content_list_v2` pages to traceable extraction HTML,
display HTML, markdown-like text, backend evidence blocks, and semantic
section/block/inline output.

实现步骤：

```text
MinerU pages
  -> 过滤 image/page_number/page_header/page_footer 这类不可用于推理的噪声
  -> title/paragraph/list/table 渲染成 HTML、Markdown 和 blocks
  -> 先把 rendered blocks 统一标注为目录页条目、正文小标题或真实 heading
  -> title 不再直接照抄 MinerU level；先对全局 title 候选做二分类聚类，高置信主章节簇才进入 h2
  -> 页面 wrapper 只保留定位属性，不主动插入 `Page N` 可见页码
  -> 全局 h2 高度档里的 title 在 HTML 中打开 section，收纳到下一个 h2 前的块
  -> level=3 的 title 在当前 section 中打开 subsection，收纳到下一个 h2/h3 前的块
  -> level>=4 的 title 降级为普通段落 block，不再让工具当成 section heading
  -> 正文小标题在 HTML 中输出为 `<p><strong>...</strong></p>`，不生成 section，也不会进入 Contents 的 outline_tree
  -> `目次` 页里的目录条目保留可见文本，但不会生成真实章节 section
  -> list/table 的主 block id 直接落在原生 ul/table 上，后续工具可按该 id 检索
  -> Markdown 输出保留 rendered block 原文顺序，不写入调试注释或聚类 metadata
  -> Markdown 标题只让全局高置信 h2 聚类簇进入 heading，其余 title 降级成加粗行
  -> `1）` / `【注意】` / `<<注意>>` / 括号编号 / 单字母标号这类正文里的小标题会降级成独立加粗行
  -> `2.日程` 这类 ASCII 点后没有空格的紧凑编号 title 会降级成正文加粗行
  -> 短的独立 `1．` / `2．` 编号 paragraph 也会作为正文小标题候选降级成加粗行
  -> MinerU 误标成 title 的提出期限/締切日期提示行会降级成正文加粗行
  -> 真标题继续按 heading 输出，正文内容保持紧跟其后
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
- `test_build_html_renders_body_subheadings_without_section_nodes`：确认正文里的 `1）`、短 `1．` 编号项和小字号 `3．` 标题只渲染为加粗段落，不会生成 heading 或 section 节点。
- `test_build_html_keeps_table_of_contents_entries_out_of_outline_headings`：确认 `目次` 页里的目录项只作为可见文本保留，不会生成 section；同名真实章节在正文页仍会生成 section。
- `test_build_markdown_demotes_deadline_title_to_body_line`：确认带日期和时间的提出期限提示行即使被 MinerU 标成 `title level=2`，也只作为正文加粗行输出，不会变成 Markdown heading 或 HTML section。
- `test_build_markdown_demotes_compact_numbered_title_with_ascii_dot`：确认 `2.日程` 这类 ASCII 点后没有空格的紧凑编号 title 会降级为正文加粗行，同时不影响英文 `1. Definitions` 这类正式标题。
- `test_build_markdown_uses_global_h2_layout_band_and_bolds_other_titles`：确认同一文档内按 title 版面特征二分类识别高置信 h2 簇，高档章节进入 `##`，其他 title 降级为加粗行。
- `test_build_markdown_clusters_h2_band_with_width_and_indent_features`：确认 h2 识别不只看高度，也会利用宽度、缩进和主章节编号形态，把版面相近但语义不同的标题分开。
- `test_build_html_skips_pages_without_visible_content`：确认空页和纯图片页不会进入 HTML。
- `test_build_html_skips_pages_with_only_page_number`：确认纯页码页不会进入 HTML、blocks 或 Markdown。
- `test_build_outputs_skip_page_footer_noise`：确认页脚版本号不会进入 extraction HTML、display HTML、blocks、Markdown 或 semantic_document。
- `test_build_blocks_from_content_list_uses_rendered_ids_for_text_list_and_table_rows`：确认 blocks 和 HTML 复用同一套可追踪 id，表格行也能作为 evidence block。
- `test_build_markdown_from_content_list_keeps_basic_structure`：确认标题和列表能转成基础 Markdown，并且输出不包含调试注释。
- `test_build_markdown_from_content_list_embeds_clustered_block_structure`：确认 Markdown 会按原文顺序输出每个 block，并保持真标题的 heading 层级。
- `test_build_markdown_from_content_list_separates_true_titles_from_body_subheadings`：确认正文里的 `1）`、`【...】` 这类小标题会被降级为加粗行，而真正的章节标题仍然保持 Markdown heading。
- `test_build_markdown_from_content_list_promotes_numbered_paragraph_body_items`：确认 MinerU 识别成 paragraph 的短 `1．`、`2．` 编号项也会进入正文小标题候选，不再作为普通段落输出。
- `test_build_semantic_document_groups_sections_blocks_and_inlines`：确认 section 包含标题和正文内容，page header 被过滤，clause 挂到最近 lead-in，inline 能切出条件片段。
- `test_build_semantic_document_from_blocks_reuses_cached_mineru_blocks`：确认已有 `document_processor.json` 里的 blocks 不重跑 MinerU 也能生成相同三层结构。
