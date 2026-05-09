# test_html_index_new.py

这份测试覆盖 `html_index.py` 对语义 HTML 的索引行为。测试输入是已经带稳定 id 的 HTML 片段，输出是 `HtmlDocument`，包括 `elements_by_id`、混排 `tree`、`tables_by_id` 和 `row_index`。

实现链路：

```text
HTML fragment
  -> build_html_document
  -> 校验可追踪元素 id 唯一且必需
  -> 建立 elements_by_id
  -> 解析 table columns / rows / row_index
  -> 构建包含 section、heading、p、list、table 的 DOM 语义 outline tree
```

## 测试函数

- `test_build_html_document_indexes_existing_ids_and_tree`：确认已有 id 会进入元素索引，和 heading 平级的段落和表格会保持同层 item，表格只暴露 label、columns 和 row_count，不暴露正文行。
- `test_mineru_figure_table_uses_block_id_and_caption_label`：确认 MinerU 风格的 `figure[data-type="table"]` 会用 figure id 作为 table id，并从 caption 类节点取得表格 label。
- `test_build_html_document_generates_and_indexes_missing_table_row_ids`：确认缺少 id 的 `table` / `tr` 会生成稳定证据 id，并同步写入表格行索引。
- `test_build_html_document_rejects_missing_required_id`：确认缺少必需 id 的可追踪元素会被拒绝。
- `test_build_html_document_rejects_duplicate_id`：确认重复 id 会被拒绝。
- `test_heading_levels_do_not_create_implicit_nested_sections`：确认 h2/h3 和段落在 flat HTML 中不会仅凭标题级别形成隐式父子关系。
- `test_section_container_keeps_its_dom_children`：确认真实 `<section>` 容器会保留自己的 heading 和段落子节点。
