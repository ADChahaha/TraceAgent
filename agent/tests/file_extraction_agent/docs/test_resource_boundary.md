# 资源职责边界测试

真实 HTML 经生成端落盘 → Agent 工具独立读取 → 验证业务包无反向依赖，损坏资源在工具预检中失败。

- `test_qa_package_does_not_import_resource_builder`：扫描 Agent 导入，禁止依赖资源生成包。
- `test_graph_state_only_carries_execution_inputs`：图状态只保存资源路径、消息和运行参数。
- `test_tools_read_prepared_files_without_builder`：禁用生成端后仍能浏览、读取文档，并拒绝读取内部清单。
- `test_tool_preflight_rejects_damaged_resource`：错误版本、无效向量和越界引用均抛出 `ValueError`。
