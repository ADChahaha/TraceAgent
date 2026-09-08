# test_tools.py

这份测试覆盖 QA completion 的模型工具集合。工具不再写字段，也不再用
`evidence://` / `path_id` / `inspect`，而是让模型在真实文件树（`DocumentFileTree`）
上执行 `ls / grep / read`。引用证据就以真实的 key 路径（如 `001-contract-.../*.md`）
为准。

实现链路：

```text
HTML -> materialize_tree 本地临时目录 -> DocumentFileTree.from_local_dir 包装
  -> build_tools(state) 暴露 ls/grep/read/search_embedding
  -> ls 只列出当前目录层的一个层级子项（key 前缀）
  -> grep 用纯 Python 遍历 .md 对象并按正则匹配（不再依赖 ripgrep）
  -> read 按 key 读取一个 .md 文件的 markdown 内容
```

测试辅助函数 `_prepare_test_state` 使用资源包的 InputDocument 生成样本文件，再用
`DocumentFileTree.from_local_dir` 把本地目录当作桶构造只读视图；不依赖 manager 或
graph 加载资源。

## 测试函数

- `test_model_path_examples_can_be_read_from_object_store`：提取模型提示中的 Markdown 引用示例，通过带 documents 前缀的对象存储替身实际读取，确认示例 key 可用，且 ls/read 不再要求本机绝对路径。
- `test_build_tools_exposes_qa_navigation_tools_only`：验证四个导航工具均暴露协程实现，模型不再看到 `inspect` 或字段抽取工具。
- `test_embedding_tool_does_not_advertise_unused_scope`：语义检索仅向模型暴露实际使用的 query、top_k 参数。
- `test_module_exports_qa_helpers_only`：验证模块公开 helper 切换到 `_ls/_grep/_read`，且 `_inspect` 已删除。
- `test_internal_tool_helpers_do_not_accept_reason_parameter`：验证工具 helper 不接收旧 `reason` 参数。
- `test_ls_and_read_use_real_file_paths`：验证 ls 返回目录项，read 接受 .md key 路径并返回正文。
- `test_ls_lists_only_the_current_tree_level`：验证 ls 只返回当前 layer，不递归展开。
- `test_grep_returns_candidate_blocks_but_not_inline_evidence`：验证 grep 纯 Python 匹配返回候选行，不含 inline selector。
- `test_read_rejects_non_file_path`：验证 read 对不存在/非文件 key 返回 `BAD_PATH` 错误。
- `test_grep_can_scope_to_directory`：验证 grep 可限定在某 key 前缀范围内搜索。
- `test_grep_matches_case_insensitively_and_limits_results`：验证 grep 大小写不敏感并限制结果数。
- `test_search_embedding_returns_result_without_event_state`：直接工具调用返回检索结果，不依赖或创建事件缓冲。
- `test_search_embedding_returns_text_and_covered_files_sorted`：用工具侧 Chunk/EmbeddingIndex 构造替身，验证候选按相似度排序。
- `test_search_embedding_rejects_empty_query`：空查询返回 BAD_QUERY 失败结果。

工具测试直接构造文档访问上下文，不再调用 manager 创建工作目录。
`test_run_tool_only_needs_operation_and_normalizes_failure`：执行入口只接收操作，异常转为统一失败对象。
