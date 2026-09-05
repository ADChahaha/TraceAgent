# test_tools.py

这组测试固定 `service.file_extraction_agent.core.tools` 包（`core/tools/` 工具包）的模型工具边界。导航工具（`ls`/`grep`/`read`）走真实文件树+ripgrep；`search_embedding` 走 embedding 索引，但测试里用替身注入（拒绝调用真实模型/OpenVINO，保证无网络、无重依赖）。

工具包结构：

```text
core/tools/
  -> __init__.py    统一接口 build_tools(state)，转出 _ls/_grep/_read/_search_embedding
                    及可替身点 _run_ripgrep/_get_embedder/_get_index
  -> base.py        共享骨架（run_tool / emit_event / record_action / expose_entries / order_key）
  -> ls.py          ls 工具
  -> grep.py        grep 工具（_run_ripgrep 用 rg 子进程）
  -> read.py        read 工具
  -> embedding.py   search_embedding 工具；查询编码与已加载索引检索
```

测试通过替换 `tools.embedding._get_embedder` / `tools.embedding._get_index` 来注入假 embedder 与假索引，替换 `tools.grep._run_ripgrep` 来注入假 rg 输出，使各工具的候选召回、事件顺序、参数校验都能离线验证。

## 测试函数

### 既有导航工具
- `test_build_tools_exposes_qa_navigation_tools_only`：断言 `build_tools` 暴露的工具名为 `["ls", "grep", "read", "search_embedding"]`。
- `test_module_exports_qa_helpers_only`：断言 `__all__` 只导出 QA 助手，不含旧的 `_inspect/_add_candidate_evidence` 等字段抽取助手。
- `test_internal_tool_helpers_do_not_accept_reason_parameter`：`_ls/_grep/_read` 不接受 `reason` 参数。
- `test_ls_and_read_use_real_file_paths`：`ls`/`read` 用真实文件路径读写。
- `test_ls_lists_only_the_current_tree_level`：`ls` 只列当前层，不递归。
- `test_grep_returns_candidate_blocks_but_not_inline_evidence`：`grep` 返回 ripgrep 候选行（monkeypatch `tools.grep._run_ripgrep`）。
- `test_read_rejects_non_file_path`：`read` 对非法路径返回 `BAD_PATH`。
- `test_grep_can_scope_to_directory`：`grep` 可限定目录（monkeypatch `tools.grep._run_ripgrep`）。
- `test_grep_fails_gracefully_when_ripgrep_missing`：ripgrep 缺失时 `grep` 优雅失败。

### `search_embedding`
- `test_search_embedding_returns_text_and_covered_files_sorted`：结果为 `ok=True`，按分数降序，每项含 `text`/`document`/`covered_files`/`chunk_id`，`text` 非空（embedding 直接返回文本内容）。
- `test_search_embedding_returns_tool_events`：验证会产生 `tool_started` 在上、`tool_completed` 在下的工具事件序列。
- `test_search_embedding_rejects_empty_query`：空 query 返回 `BAD_QUERY`，不触发检索。
