# test_html_index_new.py

这份测试覆盖新的 semantic HTML virtual tree 索引。输入是多个带文件名的 HTML 文档，输出是只读虚拟文件树、路径索引、Markdown 读取视图和 evidence selector 校验能力。

实现链路：

```text
documents(filename + html)
  -> build_html_document
  -> 每个文档生成 /001-filename-title 目录
  -> heading 生成 section 目录
  -> paragraph/list/table 生成 .md/.list/.table 文件
  -> read_markdown / paragraph_anchors / query_table / validate_evidence 按路径工作
```

## 测试函数

- `test_build_html_document_builds_virtual_tree_for_multiple_documents`：确认多文档会生成编号根目录，同名文件和同名 title 不冲突，同名 section、重复 paragraph snippet、list 和 table 都有稳定路径。
- `test_tree_view_respects_depth_and_file_kinds`：确认 `tree_text(path, depth)` 会按 depth 控制展开，并显示 `.md/.list/.table` 文件。
- `test_paragraph_anchors_use_sentence_ids_without_polluting_read`：确认 paragraph `read_markdown` 只返回正文，不带句子编号；`paragraph_anchors` 单独返回 `Sxxx`。
- `test_list_markdown_uses_item_numbers_and_nested_numbers`：确认 list Markdown 带 `Ixxx` 编号，嵌套 item 保留层级编号，并可作为 evidence selector 校验。
- `test_list_markdown_reports_has_more_against_top_level_items`：确认 list 分页的 `has_more` 按顶层 item 总数判断，而不是只看当前页。
- `test_table_markdown_uses_row_numbers_and_supports_pagination`：确认 table Markdown 带 `Rxxx` 行号，并支持 offset/limit 分页。
- `test_query_table_only_accepts_table_paths_and_keeps_original_row_numbers`：确认 SQL 查询只接受 `.table` path，返回查询命中行的原始 `Rxxx` 编号。
