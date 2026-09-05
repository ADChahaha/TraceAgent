# test_tools.py

这份测试覆盖 QA completion 的模型工具集合。工具不再写字段，也不再用
`evidence://` / `path_id` / `inspect`，而是让模型在真实文件树（`DocumentFileTree`）
上执行 `ls / grep / read`。引用证据就以真实 `.md` 文件路径为准。

实现链路：

```text
GraphState 持有 DocumentFileTree
  -> build_tools(state) 暴露 ls/grep/read/search_embedding
  -> ls 只列出当前目录层的一个层级子项
  -> grep 用 ripgrep 在 scope 目录（默认根）跑，输出原样 stdout
  -> read 读取一个 .md 文件的 markdown 内容
```

说明：测试通过 `prepare_completion_state` 用 `list[InputDocument]` 与
`list[DocumentQaMessage]` 构造强类型输入，直接产出 `GraphState`。

## 测试函数

- `test_build_tools_exposes_qa_navigation_tools_only`：验证模型看到 `ls` / `grep` / `read` / `search_embedding`，不再有 `inspect` 或字段抽取工具。
- `test_module_exports_qa_helpers_only`：验证模块公开 helper 切换到 `_ls/_grep/_read`，且 `_inspect` 已删除。
- `test_internal_tool_helpers_do_not_accept_reason_parameter`：验证工具 helper 不接收旧 `reason` 参数。
- `test_ls_and_read_use_real_file_paths`：验证 ls 返回真实目录项，read 接受绝对 `.md` 文件路径并返回正文。
- `test_ls_lists_only_the_current_tree_level`：验证 ls 只返回当前 layer，不递归展开子目录或 .md 文件内容。
- `test_grep_returns_candidate_blocks_but_not_inline_evidence`：验证 grep 走 rg 原样返回候选行，不含 inline selector。
- `test_read_rejects_non_file_path`：验证 read 对不存在/非文件路径返回 `BAD_PATH` 错误。
- `test_grep_can_scope_to_directory`：验证 grep 可限定在某个 section 目录内搜索。
- `test_grep_fails_gracefully_when_ripgrep_missing`：验证 rg 不在 PATH 时返回 `RIPGREP_MISSING` 错误。

`test_search_embedding_returns_result_without_event_state`：直接工具调用返回检索结果，不依赖或创建事件缓冲。

- `test_search_embedding_returns_text_and_covered_files_sorted`：候选按相似度排序，保留正文、来源和覆盖文件。
- `test_search_embedding_rejects_empty_query`：空查询返回 BAD_QUERY 失败结果。

资源基础实现导入迁移到 `service.document_resources`。

工具测试直接构造文档访问上下文，不再调用 manager 创建工作目录。
