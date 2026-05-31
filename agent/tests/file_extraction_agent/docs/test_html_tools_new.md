# test_html_tools_new.py

这份测试覆盖 QA completion 的模型工具集合。工具不再写字段，而是模仿 code agent 阅读项目的方式，在多文档 virtual tree 上执行 `ls / grep / read / inspect`。

实现链路：

```text
DocumentQaCompletionInput
  -> GraphState 持有 HtmlDocument
  -> build_tools(state) 暴露 ls/grep/read/inspect
  -> ls 只列出当前 document/section 的一层子节点，其中 h1 也会作为 section 目录出现
  -> grep 可限定到 h1/h2/... section，返回候选 block locator 和 preview
  -> read 打开 block 或同 section 下连续 range
  -> inspect 把 block 展开成 Sxxx/Ixxx/Rxxx inline evidence
```

## 测试函数

- `test_build_tools_exposes_qa_navigation_tools_only`：验证模型只看到 QA 导航工具，不再看到字段抽取工具。
- `test_module_exports_qa_helpers_only`：验证模块公开 helper 已切换到 `_ls/_grep/_read/_inspect`。
- `test_internal_tool_helpers_do_not_accept_reason_parameter`：验证工具 helper 不接收旧 `reason` 参数。
- `test_ls_and_read_use_evidence_locators`：验证 ls/read 使用 `evidence://` locator，并拒绝裸 path id。
- `test_ls_lists_only_the_current_tree_level`：验证 ls 只返回当前层，不递归展开下级 section 或正文 block，避免一次工具调用塞入过多无关结构。
- `test_grep_returns_candidate_blocks_but_not_inline_evidence`：验证 grep 只返回候选 block，不返回 inline selector。
- `test_grep_can_scope_to_section_locator`：验证 grep 可以限定在某个 section 范围内搜索；当 `h2` 位于 `h1` 下时，scope locator 会包含 `h1 -> h2` 的层级。
- `test_read_accepts_consecutive_sibling_range_locator`：验证 read 支持同一 section 内相邻 block 的 range locator。
- `test_inspect_expands_paragraph_list_and_table_to_inline_links`：验证 inspect 会把 paragraph/list/table 展开成句子、列表项和表格行级 evidence link。
- `test_inspect_rejects_section_and_inline_locators`：验证 inspect 只接受 readable block locator，拒绝 section 和已 inline 的 locator。
