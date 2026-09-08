# 共享 agent 协议

agent_proto 与 agent、backend 同级，保存服务间的唯一 gRPC 契约，不依赖任何业务服务。

```text
agent_proto/agent.proto
  → 从仓库根目录运行固定版本 grpc_tools.protoc
  → agent_pb2.py / agent_pb2.pyi / agent_pb2_grpc.py
  → 独立构建 traceagent-protocol wheel
  → agent 注册服务；backend 或其他调用方导入生成的客户端
```

- Python 导入名为 agent_proto，网络服务名为 traceagent.v1.AgentService。
- 业务方法为 PrepareResources、ChatCompletion、CancelCompletion；不提供问答查询或能力查询。旧 GetCompletion、GetCapabilities 调用返回 UNIMPLEMENTED；问答进展与终态由原事件流交付，探活使用标准 Health 服务。
- 运行依赖只有 grpcio 和 protobuf；协议源码和生成绑定一起随独立 wheel 发布，不复制进 agent wheel。
- agent 声明 traceagent-protocol 依赖；本仓库安装时先提供本地共享包，避免依赖不存在的公共发布版本。backend 业务代码本次不改。
- 包含生成代码的目录本身映射为 Python 包 agent_proto；setuptools 仅打包该包，不发现 agent/backend。
- 协议修改后重新生成并检查兼容性；生成失败由 protoc 非零退出报告，运行版本过旧由生成绑定在导入时拒绝。
- RunOptions 只保留 tool_execution_timeout（编号 2）；已删除的 max_tool_calls 名称及编号 1 均保留为 reserved，避免后续复用。旧客户端的该字段会作为未知字段忽略。
- 打包和生成同步测试暂由 agent/tests/test_packaging.py 验证，对应说明在 agent/tests/docs/test_packaging.md。

- CompletionEvent 新增 message_id、delta、attempt、max_attempts、retry_delay_ms（15–19），支持模型增量和指数退避通知。字段追加可解码，但旧 model_message 被 started/delta/done 替代属于业务契约变更，消费端需同步升级。
