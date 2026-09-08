# Agent gRPC API

服务名为 `traceagent.v1.AgentService`，协议见 [agent.proto](../../agent_proto/agent.proto)。调用方先准备文档，再保存资源定位数组并用于每轮问答：

```text
PrepareResources(files) → 解析与索引构建 → resource_path([{type, location}]) + documents
ChatCompletion(resource_path + messages) → 校验资源 → 单轮执行 → CompletionEvent 流
CancelCompletion(completion_id) → 立即确认取消请求 → 原问答流随后收尾
```

`resource_path` 是 `repeated ResourceRef`，每项 `{type, location}`，location 为
`s3://<bucket>[/<key>]`。type 取值：`documents`（Markdown 文件树）、`index`（embedding 索引）、
`raw`（原始上传文件，每个文件一项）。资源发布在独立的 storage 服务上。

agent 的 HTTP 路由已移除。backend 尚未适配 gRPC，以下示例使用生成的 Python 客户端。

## 准备文档和问答

先安装仓库根目录的共享包（`pip install -e ./agent_proto`）。agent 和后端均从 agent_proto 导入协议，调用方不需要安装 agent 业务包：

```python
from pathlib import Path
import grpc
from agent_proto import agent_pb2 as pb, agent_pb2_grpc

with grpc.insecure_channel("127.0.0.1:8001", options=[
    ("grpc.max_send_message_length", 64 * 1024 * 1024),
    ("grpc.max_receive_message_length", 64 * 1024 * 1024),
]) as channel:
    client = agent_pb2_grpc.AgentServiceStub(channel)
    source = Path("contract.docx")
    resource = client.PrepareResources(pb.PrepareResourcesRequest(files=[
        pb.UploadedFile(filename=source.name, content=source.read_bytes()),
    ]), timeout=1200)
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

PrepareResources 为一元 RPC：一次传入全部文件的 filename/bytes，按后缀选择 PDF 或 DOCX；等待全部解析和资源发布后返回 resource_path（[{type, location}] 数组）与 documents(filename/html)。没有分块上传。请求、响应各受配置消息上限约束，上传 bytes 与返回 HTML 都要计入大小。任一文件处理失败则整组失败，不返回可用定位；已发布资源不会随问答结束删除。

## 问答请求

ChatCompletion 为服务端流 RPC。输入转换为现有 DocumentQaMessage、RunOptions 和 ModelConfig，然后交给 CompletionManager：

- completion_id：1–128 位，以字母或数字开头，其余允许字母、数字、下划线、短横线；活动 ID 不可重复。
- resource_path：repeated ResourceRef，必须同时包含 documents 与 index 定位（同 bucket）；缺失、损坏、版本错误或引用越界均拒绝，不自动重建。
- messages：非空，支持 system/user/assistant/tool，保留完整历史，不自动摘要或裁剪。tool 必须有 tool_call_id。
- QaMessage.tool_calls_json：可选 JSON 数组，内容为原历史工具调用；tool_call_id、name 使用独立字段。
- run_options：可选，只提供 tool_execution_timeout，默认 60 秒；显式 0 不会被替换成默认值。已删除 max_tool_calls。
- model_config：可选，字段与内部 ModelConfig 对应；未提供时沿用模型环境配置。嵌套配置优先于兼容的扁平 base_url/api_key/openai_api_key/model/api_transport/temperature/top_p/top_k。
- 可选标量使用 protobuf presence 区分“未传”和零值。stream 字段保留，但该 RPC 始终流式返回。
- 不定义旧 documents、metadata、memory、task_spec 字段；protobuf 的未知字段处理遵循协议自身规则，不提供旧 JSON 请求兼容。

## 问答事件

运行时逐条 yield 事件字典，接口层转换为 CompletionEvent，gRPC 自行分帧；不再套 SSE 文本。seq 从 1 连续递增，每条流绑定一个 completion，不重复携带 completion_id。

| type | 内容 |
| --- | --- |
| completion.created | 开始执行，status=in_progress |
| source_indexed | 启动确认，result_json 为 `{"ok":true}`，不返回文档树 |
| model_message.started | message_id；每次实际请求独立，在首次输出被观察到时发送 |
| model_message.delta | message_id、delta；新增可见文本 |
| model_message.done | message_id、content、tool_calls、tool_call_count、is_final、可选 stop_signal |
| model_request.retrying | message_id（失败尝试）、attempt（下一次，2–5）、max_attempts=5、retry_delay_ms、error |
| tool_started | tool、tool_call_id、args_json |
| tool_completed / tool_failed | 对应调用的 args_json、result_json |
| completion.completed / completion.cancelled / completion.failed | 唯一业务终态、status、可选 error/error_message |

args_json、result_json 及 ToolCall.args_json 用 JSON 字符串保留动态结构、大整数和 null；客户端用 json.loads 解码。其余固定字段使用 protobuf 类型，可选字段可用 HasField 判断。最终回答由 is_final=true 标记；工具调用 ID 仍用于配对，模型引用 documents 下的真实 Markdown key 路径。

每次逻辑模型调用最多尝试五次，始终使用同一配置；指数退避公式为 min(0.5 × 2^(失败次数−1), 8) × (1 − 0.25 × random()) 秒；四次等待分别约 375–500、750–1000、1500–2000、3000–4000 ms。重试通知在等待结束前发出；第五次失败以 completion.failed 结束。SDK 内层重试关闭，旧 model_config.max_retries / MODEL_MAX_RETRIES 暂保留解析但不再控制请求次数。

按 message_id 追加 delta，done.content 替换/确认完整正文，不再追加。收到 retrying 将关联旧消息标记失败；下一次 started 使用新 ID，正文不能拼接。失败的部分文本只供展示，不作为完整 assistant 历史回传。取消或失败可能没有 done。旧 model_message 消费端必须升级；本次只更新 agent 与共享协议，不宣称 backend/前端已完成适配。

## 取消与连接生命周期

```python
response = client.CancelCompletion(
    pb.CompletionRequest(completion_id="cmp_001"), timeout=2,
)
print(response.status)
```

业务取消立即返回 cancelling，不等待模型或工具退出。重复取消返回当前状态；完成先发生时返回实际终态，注册项移除后返回 not_found。

```text
CancelCompletion
  → manager 找到本轮 runtime → 锁内设置取消标志 → 返回
  → 原问答流按 FIFO 发出已提交事件
  → 无活动工具批次：立即唤醒 consumer
  → 有活动工具批次：先配齐结果，不再请求下一轮模型
  → completion.cancelled → 关闭流、移除注册项
```

要接收收尾事件，保持原问答流打开。客户端直接 stream.cancel()、断连或 deadline 到期，表示放弃这条 RPC：回调绑定本轮 CompletionRuntime 的 disconnect，通知运行时停止后续生产并唤醒 consumer，由 finally 关闭事件迭代器并通知 manager 清理注册项。连接已断时不保证发送业务终态，也不等待工具结果补齐。

模型请求与工具调度使用协程。无活动工具批次时，取消终态发出后会取消生产协程并关闭模型流；已有工具批次仍先完成收尾。取消本地协程不保证远端模型服务立即停止计算。工具内同步文件操作、OCR 和 embedding 不能通过协程取消强行终止；客户端放弃资源准备 RPC 后，完成时可能留下已发布资源。

## 探活和错误

- agent 不提供问答查询接口；本轮进展与终态通过 ChatCompletion 事件流返回，历史查询由 backend 管理。
- 标准 grpc.health.v1.Health/Check：服务名为空或 traceagent.v1.AgentService 时返回 SERVING，仅用于进程探活，不检查模型可用性。

| 情况 | 响应 |
| --- | --- |
| 上传类型/参数、消息或资源校验失败，活动 ID 重复 | INVALID_ARGUMENT，首事件前返回 |
| 文档解析、资源准备或问答初始化异常 | INTERNAL |
| 开始执行后的模型/工具循环异常 | 原流的 completion.failed；普通工具失败可继续执行 |
| 消息超过配置上限 | RESOURCE_EXHAUSTED |
| 客户端直接取消或 deadline 到期 | 客户端观察 CANCELLED / DEADLINE_EXCEEDED |

每次 RPC 应设置符合 OCR、embedding 或问答耗时的 deadline；取消请求使用独立短超时。不要盲目重试资源准备或问答创建：响应丢失时服务端可能已执行，本版不提供持久幂等或事件重放。

部署参数、消息上限和协议生成命令见 [README](../README.md)。问答内存队列仍未设置容量上限；本次未引入多实例路由、持久任务或新的资源生命周期。

重试优先采用有效 retry-after-ms / Retry-After（秒数或 HTTP 日期，大于 0 且不超过 120 秒）；无效值回退到随机指数退避。retry_delay_ms 是本次实际等待时间的毫秒表示。
