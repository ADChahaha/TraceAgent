# 资源职责边界测试

真实 HTML 经生成端落盘 → Agent 工具独立读取 → 验证业务包无反向依赖，损坏资源在工具预检中失败。

- `test_qa_package_does_not_import_resource_builder`：扫描 Agent 导入，禁止依赖资源生成包。
- `test_graph_only_keeps_messages_with_options_bound_outside`：从 graph.py 构图，使用 messages.py 转换历史，注入 model_invocation.py 与 executor.py 的执行函数；图输入与输出只保存消息，历史问题和模型回答均保留。
- `test_tools_read_prepared_files_without_builder`：禁用生成端后仍能浏览、读取文档，并拒绝读取内部清单。
- `test_tool_preflight_rejects_damaged_resource`：错误版本、无效向量和越界引用均抛出 `ValueError`。
