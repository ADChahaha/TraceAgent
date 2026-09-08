# 文本流式输出与取消收尾草案

状态：模型原生流式与固定配置重试已实施；工具取消有界收尾、backend/前端适配仍待实施。当前行为以 [DESIGN.md](DESIGN.md) 为准。

已采用后续讨论修订：graph 使用 messages/updates 原生通道；agent 每次单次请求，失败通过状态更新转入 retry_wait；同一配置最多五次，指数退避 0.25、0.5、1、2 秒。每次实际尝试使用新 message_id，失败后可以重试，前端不得拼接失败尝试文本。工具取消章节保留为后续草案。

## 基础思路

模型 chunk 到达后立即输出文本增量，同时聚合完整 AIMessage；图只保存完整消息。
取消时停止模型与工具调度，保留已经完成的工具结果，为未完成调用补充 aborted 结果，
在有限时间内结束本轮。agent 输出事件，backend 负责持久化和下一轮历史组装。

```text
ChatCompletion(resource_path, messages)
  → CompletionManager 校验资源、装配模型并注册 CompletionRuntime
  → loop.run_qa_stream 初始化 ToolWorkspace、工具和模型消息
  → graph 消费原生 messages/updates，为每次实际请求分配 message_id
  → model_invocation 消费 provider.astream()
      ├─ LangChain 原生消息回调 → graph messages 通道 → loop → Runtime 队列 → seq → gRPC
      └─ 聚合完整 AIMessage → 校验 → MessagesState → model_message.done
  → 有 tool_calls：executor 执行工具，返回完整 ToolMessage 结果
  → graph 根据取消信号或模型终止信号决定继续 / 结束
  → Runtime 提交唯一 completion 终态，移除注册项
```

本次设计保持 gRPC、资源定位、文档处理和 embedding 存储格式不变；工具参数不做增量展示。
CancelCompletion 仍返回 `{id, status}`，不增加完整 Response 快照接口。

## 对外事件

将原 `model_message` 替换为以下三个事件，其他现有事件保留：

| type | 字段 | 语义 |
| --- | --- | --- |
| model_message.started | message_id | 本条模型消息开始，只发一次 |
| model_message.delta | message_id、delta | 本次新增可见文本，出现零次或多次 |
| model_message.done | message_id、content、tool_calls、tool_call_count、is_final、可选 stop_signal | 完整消息通过校验后的快照 |

所有事件沿用本流递增的 seq，不重复携带 completion_id。message_id 在一次实际请求中稳定，
每次重试创建新 ID 和 started；started 在首次观察到该请求输出时发送。delta 不是累计正文，也不保证恰好对应一个 token。
首版仅处理可见文本，不输出隐藏推理；没有文本的工具调用消息允许 started 直接进入 done。

```jsonl
{"type":"model_message.started","seq":3,"message_id":"msg_001"}
{"type":"model_message.delta","seq":4,"message_id":"msg_001","delta":"付款期限"}
{"type":"model_message.delta","seq":5,"message_id":"msg_001","delta":"为30天。"}
{"type":"model_message.done","seq":6,"message_id":"msg_001","content":"付款期限为30天。","tool_calls":[],"tool_call_count":0,"is_final":true}
{"type":"completion.completed","seq":7,"status":"completed"}
```

前端按 message_id 追加 delta；done 的 content 用来确认或替换完整内容，不能再次追加。
done 只结束一条消息，整轮状态由 completion 终态决定。失败或取消可能没有 done，
前端保留已显示文本并标记为中断，不把它当作正常完成的回答。

工具取消首版复用 `tool_failed`，通过稳定错误码区分主动中断与执行失败：

```json
{"type":"tool_failed","seq":12,"tool":"read","tool_call_id":"call_001","args":{"path":"documents/0001-contract/0001-block.md"},"result":{"ok":false,"errors":[{"code":"TOOL_ABORTED","message":"aborted by user"}]}}
```

上例是业务事件字典；protobuf 仍使用 args_json/result_json 编码动态内容。
客户端把 TOOL_ABORTED 展示为“已中断”。内部 ToolMessage 使用 status="error"、相同 call ID、
原名称与参数，并在 content/artifact 中携带同一结果，不伪造工具成功。

## graph 与模型调用层（已实施）

`model_invocation.py` 单次请求返回 AIMessage 或 ModelCallFailure；CancelledError 保持传播并关闭 provider 流。模型装配只保留文件/环境选定的配置，SDK 重试关闭，不动态切换 API 或改用非流式。

```text
agent 调用一次固定模型
  → 每个 chunk 通过 LangChain 原生回调进入 messages 通道
  → 完整响应聚合并校验，成功写入 messages
  → 失败返回 ModelCallFailure，更新 QaState 的次数、失败信息和退避时间
  → updates 转成 ModelRetry，Runtime 包装 model_request.retrying
  → retry_wait 等待 0.25、0.5、1、2 秒，再进入 agent
  → 第五次失败返回 ModelFailed，Runtime 输出 completion.failed
```

`graph.astream(stream_mode=["messages", "updates"])` 合并文本增量与节点结果；图内只将校验通过的完整消息加入历史，额外状态字段保存重试控制。工具完成后的下一次模型请求从第一次计数。失败尝试的局部文本不回传模型；前端按新 message_id 分开显示重试正文。

`model_request.retrying` 包含失败尝试的 message_id、下一次 attempt、max_attempts=5、retry_delay_ms 和 error。通知先于退避结束输出；取消模型或退避不会触发重试。模型消息/增量由 graph 转成内部类型，loop 只转发，stream_completion_events 负责业务事件字典。

## 取消信号与工具结果裁定（待实施）

新增运行内共享的 RunControl，放在图状态之外，由 Runtime 创建并注入 graph/executor。
它封装线程安全取消标志、可 await 的取消通知，以及当前 ToolBatch 的结果快照。
跨线程 terminate 使用 call_soon_threadsafe 唤醒事件循环，不直接操作异步生成器。

ToolBatch 保存本批调用 ID、原名称/参数及每项已裁定的 ToolMessage，仅存活于本轮，
不是全局注册表或持久化历史。每项只能从 pending 进入一个结果状态；正常完成和取消
竞争同一裁定入口，先完成裁定者生效，之后的迟到结果不能覆盖它。

```text
executor 收到完整 tool_calls
  → 注册本批调用，检查取消标志
  → 为允许启动的调用创建协程
  → 等待工具完成 / 共享执行 deadline / 取消通知
  → 正常完成：立即保存完整结果到 ToolBatch（对外仍按整批交付）
  → 取消：先收集已经完成的协程结果，再 cancel 未完成协程
  → 在统一收尾期限内保留竞争完成的真实结果
  → 剩余 pending 调用裁定为 TOOL_ABORTED
  → 按原调用顺序返回完整 ToolMessage 批次
```

真正的工具超时仍使用超时错误；取消不能覆盖已完成的成功或失败结果。
协程不响应取消时不无限 await gather；注册受控清理回调回收异常，并切断它向本轮写结果的能力。
同步 to_thread 工作和已发出的远端请求可能继续执行；TOOL_ABORTED 表示本轮不再等待或采用其结果，
不表示底层计算已经停止，也不撤销已经发生的副作用。

## CompletionRuntime 的后续取消改法（待实施）

保留 producer、FIFO 队列、consumer 分配 seq、manager 按对象身份移除注册项的机制。
`stream_completion_events` 将内部消息对象转换成三个 model_message 事件；Runtime 不重复聚合正文。

带 tool_calls 的 done 与对应 tool_started 必须作为同一发布单元，在 Runtime 锁内检查取消并入队，
同时登记这批已发布调用。工具得到发布确认后才允许执行，避免 done 已发但工具调用记录缺失，
也避免取消已经生效却又启动未发布工具。这里 tool_started 表示调用已受理，不能承诺底层操作已开始。

```text
CancelCompletion(id)
  → manager 找到 runtime → terminate 锁内标记 cancelling → 立即返回 {id, status}
  → 唤醒 RunControl；拒收新的模型 started/delta/done
  → graph 停止模型调用或 executor 中断工具，保留已裁定结果
  → Runtime 接收已发布批次的收尾结果
  → 批次补齐后提交 completion.cancelled
  → 关闭 producer/图流并移除注册项
```

已入队事件按 FIFO 发出；取消后的新模型输出被拒收。工具收尾只接受已发布批次，
每个 call ID 对外最多交付一次结果，completion 终态之后不再接受任何业务事件。
正常 completed 已先提交时保留 completed；否则已受理的取消优先于后续普通失败。
移除“producer 退出就默认为 completed”的兜底，异常退出必须按实际原因收口。

拟采用一个统一的 **100 ms 协作收尾宽限期**，从事件循环处理取消通知时开始计算，
不按工具数量累加；这是参照 Codex 的内部初始值，不是对网络交付或进程退出的硬时限。
期限到达时，Runtime 从 ToolBatch 取得已完成结果，为已发布但未裁定调用补 aborted，
排出尚未交付的结果后提交 cancelled，再取消仍未退出的 producer。
Runtime 和 executor 共用同一结果裁定入口，不能各自生成一份结果。

因此 `_cancel_deferred` 的“等待真实批次完成”语义会删除；保留的是短暂、有界的取消收尾。
最小必要的批次快照用于期限兜底，不再只是 `_pending_tool_ids` 集合。

断连/deadline 仍与业务取消分开：标记停止并清理，不等待对外事件送达。
原流必须保持可用才能收到 cancelled；初始化尚未完成时的取消交接继续沿用当前对象身份保护。
Python 协程取消是协作式的，不能照搬 Rust abort 的强制结束保证；任何同步阻塞都不得放在事件循环中。

## 历史记录归属

Codex 的“写入历史”不能直接等同于本服务已经持久化：agent 当前只保存运行时，
每轮 messages 由调用方传入，backend 才拥有跨轮历史。

```text
model_message.done → backend 保存完整 assistant 消息及 tool_calls
tool_completed / tool_failed → 保存关联 call ID 的 tool 消息（含 TOOL_ABORTED）
completion.cancelled → 保存本轮状态与中断标记
下一轮 → backend 传入已配对历史 → messages.build_qa_messages 转换 → 模型获知中断
```

未收到 done 的局部文本保存为 UI 草稿，不默认作为完整 assistant 消息回传模型。
中断标记应使用 backend 生成、模型可见的说明记录，拟表达“上一轮被用户中断，部分操作可能已执行”。
具体持久化字段需在阅读 backend 设计后确认，不在 agent 中新增会话数据库。

断连时不能保证 backend 收齐所有工具结果；缺失结果应标记为“结果未知”，不能编造成功，
也不能认定工具没有执行。没有完成 backend 的记录与回传适配前，只能宣称 agent 事件契约完成，
不能宣称已实现跨轮中断历史。

## 实施范围与验收

拟修改核心文件：contracts.py、model_invocation.py、graph.py、executor.py、loop.py、
completion_runtime.py；按需要在现有核心目录增加 RunControl/ToolBatch 的独立实现文件。
manager 继续只负责注册与取消转发。路由、共享 agent.proto 和生成绑定同步新增 message_id/delta。
旧 model_message 被替换属于消费端行为变更；agent/backend/前端必须协调升级，不能只新增字段就宣称兼容。
模型流式、固定配置重试及协议字段已实现；工具有界取消与消费端适配属于后续范围。

按 red → green → refactor 分阶段实施：

1. 模型与图：阻塞模型第二个 chunk，证明第一个 delta 在模型结束前已交付；验证 done 完整内容、顺序、无重复及无文本工具调用。
2. 重试：同一配置最多五次，失败经 updates 输出重试通知，指数退避；每次尝试独立 started/ID，失败不发 done，局部文本不进入历史；取消关闭 provider 流。
3. executor：真实完成结果保留；取消未完成调用生成 TOOL_ABORTED；完成与取消竞态只产生一个结果；迟到线程不能覆盖；收尾不等待工具执行超时。
4. Runtime：模型发布与取消竞态、统一宽限期兜底、工具结果配齐、FIFO seq、唯一终态、重复取消、断连与未迭代清理。
5. gRPC：真实流验证首个增量及时到达、字段编码、cancel 立即确认和原流最终收尾；同步共享协议生成与打包检查。
6. backend/前端：delta 不重复显示；aborted 正确展示与持久化；下一轮包含原 tool_call 和对应中断结果；断连缺失结果标为未知。

优先扩展现有 test_loop.py、test_graph.py、test_async_execution.py、test_resource_loop.py、
运行时和路由测试；新增或修改后立即同步各自 tests/docs 下的一一对应说明。
使用可控 Event/Barrier 验证时序，避免用长 sleep 或要求墙钟精确等于 100 ms 的脆弱测试。
必要时使用真实 DOCX 准备资源并通过真实 RPC 验证，模型/embedding 使用替身。

实现后同步 DESIGN.md、API.md、README、agent_loop.md、flowchart.md 和相关测试文档。
DEVLOG 条目在验证后单独征求批准。已实施行为见 DESIGN.md；工具取消的有界收尾尚未实现，不能据此宣称底层工具资源已全部回收。

## 参考实现

核对版本：Codex 稳定版 0.153.4 与主分支 d6489472（2026-09-08）；这里只借鉴其取消收尾语义。

- [工具取消与已完成结果保护](https://github.com/openai/codex/blob/d6489472f3c15e87d2d7763a5fde033545c530f8/codex-rs/core/src/tools/parallel.rs#L179-L208)
- [中断结果进入下一轮历史的测试](https://github.com/openai/codex/blob/d6489472f3c15e87d2d7763a5fde033545c530f8/codex-rs/core/tests/suite/abort_tasks.rs#L207-L300)
- [轮次取消及有界收尾](https://github.com/openai/codex/blob/d6489472f3c15e87d2d7763a5fde033545c530f8/codex-rs/core/src/tasks/mod.rs#L902-L973)
