# 资源准备与问答请求

返回 [Agent gRPC API](../API.md)。

## Python 调用示例

先安装仓库根目录共享协议包（`pip install -e ./agent_proto`）。调用方从 `agent_proto` 导入协议，无需安装 agent 业务包：

```python
from pathlib import Path
import grpc
from agent_proto import agent_pb2 as pb, agent_pb2_grpc

with grpc.insecure_channel("127.0.0.1:8002", options=[
    ("grpc.max_send_message_length", 64 * 1024 * 1024),
    ("grpc.max_receive_message_length", 64 * 1024 * 1024),
]) as channel:
    client = agent_pb2_grpc.DocumentResourceServiceStub(channel)
    source = Path("contract.docx")
    resource = client.PrepareResources(pb.PrepareResourcesRequest(files=[
        pb.UploadedFile(filename=source.name, content=source.read_bytes()),
    ]), timeout=1200)
with grpc.insecure_channel("127.0.0.1:8001", options=[
    ("grpc.max_send_message_length", 64 * 1024 * 1024),
    ("grpc.max_receive_message_length", 64 * 1024 * 1024),
]) as channel:
    client = agent_pb2_grpc.AgentServiceStub(channel)
    stream = client.ChatCompletion(pb.ChatCompletionRequest(
        completion_id="cmp_001",
        resource_path=resource.resource_path,
        messages=[pb.QaMessage(role="user", content="付款期限是多少？")],
    ), timeout=300)
    for event in stream:
        if event.type == "model_message.delta":
            print(event.delta, end="", flush=True)
        if event.type.startswith("completion."):
            print(event.type)
```

## `DocumentResourceService.PrepareResources`

- 一元 RPC：一次传入全部 `filename`/`bytes`，按后缀选 PDF/DOCX，全部解析发布后返回 `resource_path`（`[{type, location}]`）。
- 文档树发布为单个 `documents.zip`（不再内联 HTML）；`index`/`manifest` 与 `raw` 各自独立对象。
- 无分块上传，请求与响应各受消息上限约束；任一文件失败则整组失败不返回定位；已发布资源不随问答删除。

## `AgentService.ChatCompletion` 请求字段

服务端流 RPC，输入转换为 `DocumentQaMessage`、`RunOptions` 和 `ModelConfig`，由 handler 直接消费 `stream_completion`：

- `completion_id`：1-128 位，以字母或数字开头，其余允许字母、数字、下划线、短横线；只做格式校验，不再用于活动去重或取消查找。
- `resource_path`：`repeated ResourceRef`，同时包含同一 bucket 下的 `documents` 与 `index` 定位；缺失、损坏、版本错误或引用越界直接拒绝，不自动重建。
- `messages`：非空，支持 `system`/`user`/`assistant`/`tool`，保留完整历史，不自动摘要或裁剪；`tool` 消息需要带 `tool_call_id`。
- `QaMessage.tool_calls_json`：可选 JSON 数组，内容为原历史工具调用；`tool_call_id`、`name` 使用独立字段。
- `run_options`：可选，只提供 `tool_execution_timeout`（默认 60 秒）；显式 0 不会被替换为默认值。已删除 `max_tool_calls`。
- `model_config`：可选，未提供时沿用模型环境配置；嵌套配置优先于兼容的扁平字段（`base_url`/`api_key`/`openai_api_key`/`model`/`api_transport`/`temperature`/`top_p`/`top_k`）。
- 可选标量使用 protobuf presence 区分未传和零值。`stream` 字段保留，但该 RPC 始终流式返回。
- 不定义旧 `documents`、`metadata`、`memory`、`task_spec` 字段；不提供旧 JSON 请求兼容。
