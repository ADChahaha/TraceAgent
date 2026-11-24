# 稳定上下文、TurnView 与 Resume 一致性

本页属 [SessionManager 架构](../SESSION_MANAGER.md)，说明模型上下文配对提交、实时投影订阅以及 `GET /resume` 一致性边界。

## 稳定模型上下文

```text
user 输入 -> 独立完整消息提交
model_message.started / delta -> 仅过程事件与展示，不落库
model_message.done -> 以完整正文为准
  -> 无工具：单条 assistant 提交
  -> 有工具：校验原始调用 ID、名称和参数，暂存待配对组
tool_completed / tool_failed -> 按原 call_id 配对实际结果
  -> 未配齐：仅保存过程
  -> 配齐：同一事务提交 assistant + 按原调用顺序排列的全部 tool
下一轮 begin -> 只读取 chat_messages，不拼接过程事件
```

- 同名工具按 ID 独立匹配，结果乱序到达不改变稳定消息顺序；未知、重复或无实际结果的终态不得补造数据。
- 组提交与事件入库同事务，失败无半组或提前广播；取消、执行失败或不完整终结丢弃未配齐组，保留此前完整消息；`completion.completed` 只收口轮次，不重复保存 assistant。

## TurnView 与 Subscription

- `TurnView` 归 runtime 所有，累积本轮用户消息、模型尝试、工具和重试状态：`delta` 追加，`done` 用完整正文覆盖，重试按 `message_id` 分开，终结时未完成 item 标为 `interrupted`。终态广播后 manager 释放 runtime 引用。
- 每个页面一条 `Subscription` 由 manager 持有；`publish` 深拷贝事件且不等待消费，溢出仅关闭该慢连接并清空队列，不影响其他页面或执行；`receive` 等待通知后取队列，心跳超时取消等待不会偷走下一条事件。
- 有界订阅不等于整个 session 固定内存上限：当前轮展示、工具配对与模型请求仍随当前工作量增长。

## `GET /resume` 一致性协议

```text
GET /resume -> manager.attach（串行命令内）：
  1. 读取已存在的 turn id 列表（冻结快照范围）
  2. 捕获 session 状态、资源、当前轮展示副本（若存在）
  3. 注册独立订阅，后续新事件入队
请求侧 build_snapshot（命令循环外）：
  4. 读取 chat_messages（按 sequence）与 chat_turns（状态和 error）
  5. 只渲染冻结列表内的历史轮并排除当前轮
  6. 附加当前轮内存副本，校验快照预算并发送 session.snapshot
  7. 消费订阅队列增量
```

- 过程事件不落库，历史轮由 `chat_messages` 与 `chat_turns` 渲染：`tool_calls_json` 还原工具调用列表，tool 消息按内容区分成功/失败；未配齐工具组不落库亦不展示，终态错误来自 `chat_turns.error`。
- 冻结 turn id 列表切分数据库前缀与订阅增量：`attach` 后新建轮次只走订阅，查询期间旧轮完成反映为数据库终态，当前轮始终以捕获副本为准，避免重复或遗漏。
- 历史查询在命令循环外执行，不阻塞 cancel；查询失败、30 秒超时或构造期间订阅溢出时释放订阅，不发送残缺快照；首帧编码后立即释放历史对象与副本。
- SSE 跟随首帧活跃轮至其终态关闭，空闲会话仅发一帧；重开页面可冷加载或复用 manager，不重建远端 gRPC call。完整格式见 [API.md](../API.md)。
