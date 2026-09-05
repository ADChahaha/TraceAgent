# 路径问答图测试

资源路径和消息 → 图内初始化 → 模型发布调用 → 完整结果批次 → 取消后结束。

- `test_path_graph_returns_complete_tool_batch_and_stops_after_cancel`：两次同名工具调用分别成功和失败，整批返回 ID、名称、参数与结果；取消仍配齐该批次结果，且不再调用下一轮模型。初始化参数不包含任务或 completion ID。

测试调用与替身模型名称同步采用 qa 命名，验证行为保持原契约。
