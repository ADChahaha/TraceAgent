# test_html_index_new.py

这份测试覆盖新的 semantic HTML virtual tree 索引。输入是多个带文件名的 HTML 文档，输出是只读虚拟文件树、路径索引、Markdown 读取视图和 evidence selector 校验能力。

实现链路：

```text
documents(filename + html)
  -> build_html_document
  -> 每个文档生成 /001-filename-title 目录
  -> 给文档目录生成 0001/0002 形式的裸 path_id
  -> 文档目录名可使用第一个 h1/title，但所有 h1-h6 都继续按层级生成 section 目录
  -> 文档直下可读 block 使用 0001.0000.xxxx 命名空间，section 内可读 block 使用 section path_id.xxxx
  -> document/section 目录和 paragraph/list/table 叶子节点都从原始 HTML 节点读取 id / data-element-id，生成 path_id -> 原始 DOM id 的 source_selectors
  -> 多个 h1 会成为文档目录下的多个一级 section，h2-h6 挂到最近更高层 section 下
  -> paragraph/list/table 生成 .md/.list/.table 文件
  -> read_markdown / paragraph_anchors / query_table / validate_evidence 按 path_id 或内部路径反查工作
```

## 测试函数

- `test_build_html_document_builds_virtual_tree_for_multiple_documents`：确认多文档会生成编号根目录，同名文件和同名 title 不冲突；首个和后续 `h1` 都会作为一级 section，同名 section、重复 paragraph snippet、list 和 table 都有稳定路径。
- `test_tree_view_respects_depth_and_file_kinds`：确认 `tree_text(path_id, depth)` 会按 depth 控制展开，并显示无同级序号前缀的 `.md/.list/.table` 文件名。
- `test_path_ids_are_stable_model_visible_locators_for_raw_paths`：确认 raw virtual path 可以映射到稳定 `path_id`，模型读取结果只暴露 `path_id` 而不暴露 raw path。
- `test_source_selectors_map_readable_path_ids_to_original_dom_ids`：确认 document/section 目录会映射到自己的 heading DOM id，paragraph/list/table 叶子节点会映射到对应原文 DOM id，让 folder evidence 可以跳到 header。
- `test_h1_sections_wrap_following_blocks_and_subsections`：确认 `h1` 会作为 section 包住后续 block，后续 `h2` 会挂到该 `h1` section 下。
- `test_pre_heading_direct_blocks_use_document_root_namespace`：确认第一个 heading 前、没有 section 包住的文档直下 paragraph/list/table 会进入 `0001.0000.xxxx` 命名空间，不和真实 section 目录同级抢编号。
- `test_bracketed_path_ids_are_rejected_instead_of_canonicalized`：确认旧 `[0000...]` 方括号格式不再被兼容或归一化，`resolve_path_id`、`canonical_path_id`、`path_id` 和 `read_markdown` 都会拒绝它。
- `test_tree_display_names_decode_percent_encoded_filenames_without_changing_raw_paths`：确认 tree 的模型可见显示名会把 `%20` 等 percent-encoded 文本解码，但内部 raw path 索引保持不变。
- `test_paragraph_anchors_use_sentence_ids_without_polluting_read`：确认 paragraph `read_markdown` 只返回正文，不带句子编号；`paragraph_anchors` 单独返回 `Sxxx`。
- `test_list_markdown_uses_item_numbers_and_nested_numbers`：确认 list Markdown 带 `Ixxx` 编号，嵌套 item 保留层级编号，并可作为 evidence selector 校验。
- `test_list_markdown_reports_has_more_against_top_level_items`：确认 list 分页的 `has_more` 按顶层 item 总数判断，而不是只看当前页。
- `test_table_markdown_uses_row_numbers_and_supports_pagination`：确认 table Markdown 带 `Rxxx` 行号，并支持 offset/limit 分页。
- `test_query_table_only_accepts_table_paths_and_keeps_original_row_numbers`：确认 SQL 查询只接受 `.table` path，返回查询命中行的原始 `Rxxx` 编号。
