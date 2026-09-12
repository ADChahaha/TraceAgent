# 资源职责边界测试

真实 HTML 经生成端发布到 storage 服务 → prepare 子进程拉取并校验资源 → 工具子进程只从 payload 还原文档树 → 验证业务包无反向依赖，损坏资源在 prepare 阶段失败。

- `test_qa_package_does_not_import_resource_builder`：扫描 Agent 导入，禁止依赖资源生成包。
- `test_graph_keeps_retry_state_with_options_bound_outside`：从 graph.py 构图，使用 messages.py 转换历史，注入 model_invocation.py 与 executor.py 的执行函数；图输入与输出只保存消息，历史问题和模型回答均保留。
- `test_tools_read_prepared_files_without_builder`：禁用生成端后，从 prepare payload 还原文档树仍能浏览、读取文档，并拒绝读取内部清单。
- `test_tool_preflight_rejects_damaged_resource`：错误版本、无效向量和越界引用都让 prepare 返回 `kind=invalid`；损坏通过 `s3_store` 改写 storage 服务中的对象实现。

图执行验证使用 ainvoke 和异步模型替身，保留原有资源边界断言。
图状态允许保存重试计数、失败和退避时长；workspace 与运行配置仍在图外。

图执行验证使用 ainvoke 和异步模型替身，保留原有资源边界断言。
图状态允许保存重试计数、失败和退避时长；资源及运行配置仍在图外。

模型装配对象重命名为 ConfiguredChatModel，明确只保存一个固定调用配置。
