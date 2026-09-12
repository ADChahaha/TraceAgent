# test_tools.py

这份测试覆盖 QA completion 的模型工具集合，以及父进程侧工具到子进程的下发协议。

工具不再在父进程持有 `ToolWorkspace`，也不再写字段或使用 `evidence://`：
`build_tools(workspace)` 返回四个 async LangChain 工具，每次调用都通过注入的
`run_operation` 把 `operation`、参数和全量 workspace payload 交给统一子进程执行。
本文件用记录型替身验证下发内容；子进程真正的读取逻辑由 `_ls/_grep/_read` 同步 helper
在本进程用本地文件树直接验证（与 worker 内执行的是同一份函数）。

## 实现链路

```text
build_tools(workspace, run_operation=fake)
  -> ls / grep / read / search_embedding 四个 @tool
  -> ainvoke(args) -> run_operation(operation=..., args=..., workspace=workspace)

worker 侧只读逻辑（本文件直接测 helper）
  -> materialize_tree 准备本地文件树 -> DocumentFileTree
  -> _ls 逐层浏览、_read 按 key 读取、_grep 纯 Python 字面匹配
```

## 测试函数

- `test_build_tools_exposes_qa_navigation_tools_only`：`build_tools` 只暴露 `ls / grep / read / search_embedding` 四个协程工具。
- `test_embedding_tool_does_not_advertise_unused_scope`：语义检索只向模型暴露实际使用的 `query`、`top_k`。
- `test_tools_forward_operation_args_and_full_workspace_to_worker`：四个工具都把各自的 operation、参数和同一份完整 workspace 下发给 run_operation，并原样返回子进程结果。
- `test_search_embedding_rejects_empty_query_without_starting_worker`：空 query 直接返回 `BAD_QUERY`，不启动子进程。
- `test_model_path_examples_can_be_read_from_object_store`：模型提示中的 Markdown 引用示例能作为对象 key 交给 `_read`，且 ls/read 描述不要求本机绝对路径。
- `test_module_exports_qa_helpers_only`：公开 helper 为 `_ls/_grep/_read`，旧 `_search_embedding`、`_get_index` 等已不再导出。
- `test_run_tool_only_needs_operation_and_normalizes_failure`：`run_tool` 正常透传结果，普通异常转统一 `ok:false`。
- `test_internal_tool_helpers_do_not_accept_reason_parameter`：`_ls/_grep/_read` 不接收旧 `reason` 参数。
- `test_ls_and_read_use_real_file_paths`：ls 返回目录项，read 接受 .md key 并返回正文。
- `test_ls_lists_only_the_current_tree_level`：ls 只返回当前层，不递归展开。
- `test_grep_returns_candidate_blocks_but_not_inline_evidence`：grep 纯 Python 匹配返回候选行，不含 inline selector。
- `test_read_rejects_non_file_path`：read 对不存在或非文件 key 返回 `BAD_PATH`。
- `test_grep_can_scope_to_directory`：grep 可限定在 key 前缀范围内搜索。
- `test_grep_matches_case_insensitively_and_limits_results`：grep 大小写不敏感并限制结果数。
