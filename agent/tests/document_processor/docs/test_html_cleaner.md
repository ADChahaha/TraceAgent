# `test_html_cleaner.py`

## 基本实现思路

这份测试覆盖 `service.document_processor.html_cleaner`。它把 docling 导出的 HTML 清理成字段抽取更适合消费的 HTML fragment。文档内容是否有意义由 docling 的 `labels` 参数决定，这里只处理 HTML 形态。

```text
docling raw html
  -> clean_semantic_html(...)
  -> 删除 html/head/body/style/script/meta 等页面壳
  -> 删除 class/style/data-* 等装饰属性
  -> 保留 id/rowspan/colspan
  -> 为缺少 id 的段落、列表、表格、表格行等块级节点补稳定 id
```

## 测什么

- 清理后的 HTML 不再包含完整页面壳、CSS 或脚本。
- cleaner 不做语义标签二次筛选，docling 输出的普通标签会保留。
- 段落、列表、表格和表格行会补上 `dp-*` id。
- `td/th` 不自动补 id，表格证据定位到 `tr` 行。
- 表格合并单元格的 `rowspan` 和 `colspan` 不会被删除。
- 空表格单元格会保留，避免破坏列对齐。
- 原始 HTML 已有的 `id` 会保留，不会被覆盖。
- 空段落、空列表项和孤立换行会保留；内容过滤不在 cleaner 做。

## 每个函数在干什么

`test_clean_semantic_html_removes_page_shell_and_attributes_only`

- 输入包含 `head/style/script/div/span/class/style/data-*` 的完整 HTML。
- 验证页面壳和装饰属性被删除。
- 验证 `div/span` 等普通标签不被 cleaner 二次筛掉。

`test_clean_semantic_html_preserves_rowspan_and_colspan`

- 输入包含合并列和合并行的表格。
- 验证 `colspan` 和 `rowspan` 在输出中保留。

`test_clean_semantic_html_keeps_empty_table_cells_for_column_alignment`

- 输入最后一列为空的表格行。
- 验证空 `td` 仍然保留，确保列数量不被清理过程改坏。

`test_clean_semantic_html_keeps_existing_ids`

- 输入节点已经有来源 id。
- 验证清理过程只删除装饰属性，不覆盖已有 id。

`test_clean_semantic_html_does_not_filter_docling_content_nodes`

- 输入空段落、空列表项和孤立 `br`。
- 验证 cleaner 保留这些节点，不在后处理阶段做内容过滤。

## 怎么跑

```bash
conda activate agent-gate
cd agent
python -m pytest tests/document_processor/test_html_cleaner.py -q
```
