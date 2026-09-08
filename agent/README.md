# Agent Service

agent 在单个进程中提供 gRPC 文档准备与路径问答。文档准备把 PDF/DOCX 转为 HTML、Markdown 文件树和 embedding 索引，并发布到独立的 storage 服务（S3 兼容）；问答复用 storage 中的资源，通过服务端流逐条返回 protobuf 事件。

```text
PrepareResources(files: filename + bytes)
  → document_processor.process → document_resources.prepare_resources
  → 发布到 storage 服务 → resource_path([{type, location}]) + documents(filename/html)

ChatCompletion(completion_id + resource_path + messages)
  → CompletionManager → 经 S3ObjectStore 读取资源 → 模型/工具循环 → 带 seq 的事件字典
  → gRPC CompletionEvent 流 → 清理本轮注册项，保留文档资源
```

本次只迁移 agent；backend 仍使用旧 HTTP 客户端，尚不能调用新服务。

## 启动与探活

从 agent 目录运行：

```bash
conda activate agent-gate
pip install -e ../agent_proto -e ".[dev,embeddings]"
python main.py --host 127.0.0.1 --port 8001
```

另一个终端可执行：

```bash
conda activate agent-gate
python main.py --check-health 127.0.0.1:8001 --timeout 5
```

探活使用标准 `grpc.health.v1.Health/Check`，成功输出 SERVING、退出码为 0，失败为 1。不再提供 HTTP 路由或 OpenAPI 页面。仓库根目录的 `scripts/start.sh` 已改用 gRPC 入口；它仍会启动未迁移的 backend。

| 参数 / 环境变量 | 默认值 | 用途 |
| --- | --- | --- |
| `--host` / `AGENT_HOST` | 127.0.0.1 | 监听地址 |
| `--port` / `AGENT_PORT` | 8001 | gRPC 端口 |
| `--workers` / `AGENT_GRPC_WORKERS` | 16 | 文档处理、初始化及工具内同步 I/O/计算的线程数，至少 1；不限制活动 RPC 流数 |
| `--max-message-bytes` / `AGENT_GRPC_MAX_MESSAGE_BYTES` | 67108864 | 单条请求和响应的 64 MiB 上限 |

服务使用 `grpc.aio`：RPC 方法与事件等待运行在事件循环中，文档处理和问答初始化通过 `asyncio.to_thread` 执行。问答流等待事件不占工作线程，也没有 workers−2 的活动流限制；模型 astream/ainvoke、图执行、工具调度和事件生产都运行在协程中，只有同步文件操作与本地计算交给线程。客户端也须配置足够的消息接收上限，尤其是多文档 HTML 响应。当前使用明文 gRPC，与原本机服务部署边界一致。

准备阶段需要 embedding 依赖；PDF 使用 MinerU，DOCX 使用 python-docx。默认 embedding 后端为 OpenVINO。问答模型配置 `BASE_URL`、`OPENAI_API_KEY`、`MODEL`；可选 `MODEL_API_TRANSPORT=responses` 或 `chat_completions`。PDF 语言由 `DOCUMENT_PROCESSOR_MINERU_LANG` 指定，默认 japan。

资源发布到独立的 storage 服务（仓库顶层 `storage/`，S3 兼容 HTTP）。agent 通过 boto3
（`S3_ENDPOINT_URL`，默认 `http://localhost:9000`）访问；先启动 storage 服务再启动 agent。
资源不会随问答完成、失败或取消而删除。注册表仍在单进程内，多进程和跨机器资源调度不在本次迁移范围。

## 协议与验证

共享协议位于与 agent、backend 同级的 [agent_proto](../agent_proto/README.md)，协议源为 [agent.proto](../agent_proto/agent.proto)。源码和绑定由独立的 traceagent-protocol wheel 发布，agent wheel 只声明依赖。后端可独立安装共享包。修改协议后，从仓库根目录重新生成：

```bash
conda activate agent-gate
python -m grpc_tools.protoc -I. --python_out=. --pyi_out=. --grpc_python_out=. agent_proto/agent.proto
cd agent
python -m pytest tests -q
```

dev 依赖固定代码生成器版本，测试会重新生成并比对绑定；不要手工修改生成文件。

- [gRPC API](docs/API.md)：客户端示例、事件和错误。
- [服务设计](docs/DESIGN.md)：通信、线程与生命周期边界。
- [资源设计](service/document_resources/docs/DESIGN.md)：资源构建和发布。
- [问答设计](service/file_extraction_agent/docs/DESIGN.md)：模型、工具批次与取消。

测试使用真实 RPC 和 DOCX，模型与 embedding 使用替身；不要求下载模型或访问真实 provider。

### 问答流式事件

模型由文件/环境配置选定，单次请求失败通过图的 retry_wait 节点采用以 0.5 秒起步、8 秒封顶并乘 0.75–1 随机系数的指数间隔退避，总共最多五次，配置保持不变。LangGraph messages 通道实时提供可见文本，updates 通道提供完整结果和重试通知。SDK 内层重试关闭。

事件为 model_message.started / delta / done 和 model_request.retrying；按 message_id 区分尝试，done 正文不能重复追加。Runtime 保留单个 producer Task、FIFO 队列与消费者；取消模型或退避会清理对应异步流。工具取消的有界收尾仍是后续设计，当前继续保留已有批次收尾规则。消费端需按新协议适配，详见 docs/API.md。

重试优先采用有效 retry-after-ms / Retry-After（秒数或 HTTP 日期，大于 0 且不超过 120 秒）；无效值回退到随机指数退避。retry_delay_ms 是本次实际等待时间的毫秒表示。
