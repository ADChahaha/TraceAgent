# 路径问答图测试

资源路径 → 创建工具上下文 → 配置工具超时 → 模型发布调用 → custom 逐项工具结果 → 取消后结束。

- `test_path_graph_streams_tool_results_and_stops_after_cancel`：验证路径只用于初始化工具上下文、超时传入 executor；逐项收到同名工具的成功和失败 ToolMessage，保留 ID、名称及参数，取消后不调用下一轮模型。

使用真实 LangGraph 和 ConfiguredChatModel，只替换资源访问器和 provider。
