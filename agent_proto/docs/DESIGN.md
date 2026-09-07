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
- 业务方法为 PrepareResources、ChatCompletion、CancelCompletion、GetCapabilities；不提供问答查询。旧 GetCompletion 调用返回 UNIMPLEMENTED，调用方应通过原问答流接收进展与终态。
- 运行依赖只有 grpcio 和 protobuf；协议源码和生成绑定一起随独立 wheel 发布，不复制进 agent wheel。
- agent 声明 traceagent-protocol 依赖；本仓库安装时先提供本地共享包，避免依赖不存在的公共发布版本。backend 业务代码本次不改。
- 包含生成代码的目录本身映射为 Python 包 agent_proto；setuptools 仅打包该包，不发现 agent/backend。
- 协议修改后重新生成并检查兼容性；生成失败由 protoc 非零退出报告，运行版本过旧由生成绑定在导入时拒绝。
- 打包和生成同步测试暂由 agent/tests/test_packaging.py 验证，对应说明在 agent/tests/docs/test_packaging.md。
