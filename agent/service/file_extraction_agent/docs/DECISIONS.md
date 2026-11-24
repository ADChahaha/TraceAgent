# file_extraction_agent 关键决策

归属 [文档问答执行设计](DESIGN.md)，记录问答内核、模型装配与工具子进程模块的长期取舍。

## 1. 无状态单轮执行，与 `document_service` 仅通过 `storage` 交接

- 决定：问答服务不导入 `document_resources`，只消费 `storage` 中已发布的 `documents.zip` 与 `index/`；不同 RPC 之间不共享可变状态，每轮完整历史由调用方通过 append-only `messages` 传入。
- 原因：支持 `agent` 与 `document_service` 独立部署及问答节点无状态水平扩展。
- 排除：在 agent 进程内维护会话与活动 completion 注册表，或在问答侧重新解析文档与重建向量。

## 2. 统一标准 `ChatOpenAI`，内层零重试且移除厂商特化分支

- 决定：模型装配统一使用标准 `ChatOpenAI`，生产固定 `streaming=True`（不自动降级），SDK 内层 `max_retries=0`（重试统一由图内 5 次退避控制）；已移除 DeepSeek 专用 `reasoning_content` / `thinking` 适配与多模型候选列表。
- 原因：防止 SDK 内层重试与图外层重试相乘放大延迟，降低厂商特化分支的长期维护成本。
- 排除：保留多模型自动回退候选列表，或为特定厂商维护专用消息字段补丁。

## 3. 每次工具调用走一次性子进程，检索端采用纯 OpenVINO 查询编码

- 决定：所有工具通过 `worker_client.run_operation` 启动一次性子进程执行；`search_embedding` 仅依赖 `openvino` + `tokenizers`（不导入 `torch`/`transformers`，冷启约 2.3s，对比 `sentence-transformers` 约 21s），取消或超时在 `finally` 直接 kill 子进程。
- 原因：以单次子进程开销换取可靠的强杀取消语义、隔离父进程内存与简化并发控制。
- 排除：在父进程加载查询模型，或首版引入复杂的常驻 worker 进程池。

## 4. 工具全异步化与原生取消传播

- 决定：工具仅保留异步 `ainvoke` 接口，取消沿 `asyncio.Task` 与 `aclosing` 自动关闭内层图与模型流；事件包装不维护 pending 配对字典。
- 原因：避免同步阻塞事件循环和手动传递停止标志漏清理子进程。
- 排除：保留 `SyncTool` 同步接口和 `should_stop`/`StopCheck` 回调轮询。
