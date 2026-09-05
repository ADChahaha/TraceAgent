# test_documents.py

表格验证链路：HTML 合并单元格 → 展开行列跨度 → 写入 Markdown → 检查金额、列位置及竖线转义。

- `test_table_preserves_merged_cells_and_wider_rows`：覆盖合并表头、跨行单元格、后续行更宽和单元格内竖线，确保内容不截断、不移列。

这份测试覆盖新的「真实文件树」materialization。输入是多个带文件名的 HTML
文档，输出是落盘的真实目录树（`DocumentFileTree`），每个 paragraph / list /
table 都写成一个 `.md` 文件，供 `ls` / `grep`(rg) / `read` 工具在真实文件
系统上操作。

边界已强类型化：`materialize_tree` 只接受
`documents: list[InputDocument]`，不再接受 dict / duck-typed object；
缺文件名或空 HTML 的语义校验仍会在 `normalize_documents` 抛出 `ValueError`。

实现链路：

```text
list[InputDocument](filename + html)
  -> materialize_tree(documents, workspace_root)
  -> 每个 document 生成 <workspace_root>/001-<filename>-<title> 目录
  -> 按 h1-h6 层级建 section 子目录
  -> paragraph/list/table 各写一个数字前缀 + slug 的 .md 文件（列表/表格整表一个文件）
  -> 目录/文件排序靠数字前缀，不靠 os.listdir
  -> DocumentFileTree.root / entries(path) / read(path) / scope_path(scope)
```

设计约定：

- 每一个 document 是 workspace_root/\<completion_id\>/0001-\<doc\> 目录。
- section 是子目录；paragraph 是 `0001-xxx.md`，list 是 `0002-xxx.md`，
  table 是 `0003-xxx.md`。数字前缀在同 section 内跨类型共享递增。
- 没有 `path_id`、`evidence://` 或句/行级 selector；引证就用真实文件路径。
- `entries`/`read`/`scope_path` 会拒绝逃出 workspace 根目录的路径。

## 测试函数

- `test_materialize_tree_writes_real_files_for_multiple_documents`：确认多文档会生成数字前缀根目录，同名文件/同名 title 不冲突，且 doc 目录名带 title slug。
- `test_tree_entries_respect_depth_and_file_kinds`：确认 `entries` 按 layer 展开，根层是 document 目录、document 层是 section 目录。
- `test_tree_writes_paragraph_list_and_table_as_markdown_files`：确认 paragraph/list/table 都写成 `.md` 文件且保留原文顺序前缀。
- `test_tree_writes_list_with_nested_markdown`：确认 list 转成 Markdown bullet，嵌套 item 保留缩进层级。
- `test_tree_writes_table_as_one_markdown_file`：确认整张 table 作为一个 .md 文件输出 Markdown 表（表头 + 分隔行 + 数据行）。
- `test_tree_orders_entries_by_numeric_prefix_not_filesystem`：确认排序靠数字前缀，不靠文件系统枚举顺序。
- `test_tree_read_rejects_paths_outside_workspace`：确认 `read` 拒绝超出 workspace 根目录的文件路径。
- `test_tree_entries_reject_paths_outside_workspace`：确认 `entries` 拒绝超出 workspace 根目录的目录路径。
- `test_materialize_tree_rejects_document_without_filename_or_html`：确认缺 filename 或空 html 会抛 ValueError。

资源基础实现导入已迁移到 `service.document_resources`；原测试行为保持不变。
