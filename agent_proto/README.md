# 共享 gRPC 协议

本目录与 agent、backend 同级：agent.proto 定义网络契约，protoc 生成 Python 消息、客户端和服务端绑定。发布包名为 traceagent-protocol，Python 导入名为 agent_proto，不依赖 agent 的业务代码。

```text
agent_proto/agent.proto → protoc → Python 绑定 → 独立 wheel → agent / backend 共同使用
```

从仓库根目录安装共享包：

```bash
conda activate agent-gate
python -m pip install -e ./agent_proto
```

调用方使用：

```python
from agent_proto import agent_pb2, agent_pb2_grpc
```

修改协议后，从仓库根目录重新生成：

```bash
conda activate agent-gate
python -m pip install -e "./agent_proto[dev]"
python -m grpc_tools.protoc -I. --python_out=. --pyi_out=. --grpc_python_out=. agent_proto/agent.proto
```

生成代码不手工编辑。协议文件与 Python 绑定一起打包，版本须与 grpcio/protobuf 运行依赖匹配。agent 安装时需要同时提供该本地包；后端接入时也只需安装此包，无需安装 agent-service。

接口内容见 [agent API](../agent/docs/API.md)，包边界见 [设计](docs/DESIGN.md)。
