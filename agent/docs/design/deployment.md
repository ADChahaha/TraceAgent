# Agent 传输、部署与取消边界

本页属 [Agent Service Design](../DESIGN.md)，说明双 gRPC 服务的启动运行模型、共享协议打包与取消语义。

## 安装与本地启动

- 仓库安装脚本同时安装 `storage` 包、agent 和 document service 的 `embeddings` 扩展依赖，补齐默认 OpenVINO 查询编码器与文档索引构建所需运行时。
- 首次使用 embedding 模型时仍需要下载模型文件。
- 启动脚本默认先启动本地 `storage`，并向各服务导出统一的 `S3_ENDPOINT_URL`；显式设置该地址时复用外部 storage。
- 所有本地服务由脚本记录 PID 并在退出时清理。

## gRPC 运行时流程

```text
document_service/main.py（默认 8002）读取监听地址、阻塞工作线程数和消息上限
  -> asyncio.run 创建 document service 事件循环，启动 grpc.aio.Server 与异步标准 Health
  -> DocumentResourceService.PrepareResources 的解析/资源构建通过 asyncio.to_thread 执行

agent/main.py（默认 8001）读取监听地址、阻塞工作线程数和消息上限
  -> asyncio.run 创建 agent service 事件循环，启动 grpc.aio.Server 与异步标准 Health
  -> AgentService.ChatCompletion 的资源预检和每个工具调用通过一次性 worker 子进程执行
  -> 取消和探活直接在事件循环处理
  -> routes 转换 protobuf 与业务对象，保留参数缺省值及显式零值
  -> handler 消费 application.stream_completion，保留业务层分配的 seq 并编码 CompletionEvent
  -> handler 使用 aclosing 关闭生成器，RPC 取消沿 await 传播
  -> SIGINT/SIGTERM 唤醒 asyncio.Event，await server.stop(5) 停服
```

## 并发、协议与消息上限

- 默认 16 个阻塞工作线程、单条请求/响应上限 64 MiB。
- 活动 RPC 流不受线程数限制，等待事件不占执行器；模型请求、重试退避、图执行和工具调度均为原生异步。
- 文档解析使用阻塞工作线程，工具计算在可 kill 的子进程中执行。
- 文件整包 bytes 上传，客户端须相应配置收发上限。固定事件字段使用 protobuf，动态参数/结果用 JSON 字符串保留大整数和 null。
- 共享协议位于同级 `agent_proto`，agent wheel 依赖 `traceagent-protocol`，不内置协议副本。协议生成器版本固定，从仓库根目录生成；测试比对绑定，并验证共享 wheel 可脱离 agent 业务包导入。

## RPC 取消语义

- 一次 `ChatCompletion` RPC 持有一轮执行。
- 客户端取消原 call、deadline 或已检测到的断连由 `grpc.aio` 取消 handler；handler 关闭事件流，取消沿模型/图等待传播，工具 `finally` 取消未完成 Task 并 kill 工具子进程。
- 没有独立 producer、事件队列、注册表或 `CancelCompletion` RPC。
- 客户端本地取消不代表远端清理已经完成，backend 仍须拒绝旧轮迟到写入。
- prepare 子进程同样在取消时清理；已创建但未消费的生成器不启动模型执行。
