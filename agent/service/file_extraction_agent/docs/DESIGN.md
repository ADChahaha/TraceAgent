# 文档问答执行设计

问答模块消费 document service 已准备的资源定位数组，执行一次模型与工具循环。资源生成由独立 document service 负责，问答包不导入 `document_resources`，只通过 `storage` 服务交接；资源读取与检索集中在工具子进程层。

```text
resource_refs([{type, location}]) + messages + model_config / run_options
  -> routes 适配普通参数 -> application.stream_completion 校验并启动 prepare 子进程
  -> worker 拉取 documents.zip 与索引，返回 workspace payload
  -> application 装配模型并消费 stream_execution -> core.loop.run_qa_stream
  -> LangGraph（agent / retry_wait / tools）产出增量、模型完成与单条工具结果
  -> application 归一化带 seq 的 CompletionEvent -> 路由编码 protobuf -> gRPC 流
```

## 主题文档

- [存储与请求](design/storage-and-request.md)：数据流、`CompletionEvent`/`JsonValue`、payload 存储与取消边界
- [图状态与循环](design/graph-and-state.md)：`QaState`、`run_qa_stream`、重试退避、`stream_mode`、`RunOptions` 与 6 文件分工
- [模型与事件](design/events-and-model.md)：`ConfiguredChatModel`/`ChatOpenAI`、`visible_text`、模型事件与并行工具批次
- [工具与部署](design/tools-and-deployment.md)：一次性 worker 进程、OpenVINO 基准、文档树引用与跨轮无状态边界

同级：[DECISIONS.md](DECISIONS.md) / [tools.md](tools.md) / [STREAMING_AND_CANCELLATION.md](STREAMING_AND_CANCELLATION.md) / [agent_loop.md](agent_loop.md) / [flowchart.md](flowchart.md)
相关：[agent API](../../../docs/API.md) / [资源设计](../../../../document_service/document_resources/docs/DESIGN.md)
