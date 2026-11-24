# 消息配对、中断边界与跨轮顺序

返回 [Backend 数据表](../table.md)。

## 配对与原子提交

```text
backend 接收 agent event，在串行路径检查本地状态
  -> 已取消或终态：丢弃迟到事件，不提交稳定消息
  -> model_message.started / delta：仅过程展示，不写 chat_messages
  -> model_message.done：以完整快照为准，不重复拼接 delta
     |- 无 tool_calls：完整 assistant 单条成组提交，不等待 completion.completed
     \- 有 tool_calls：按本轮 message_id 暂存 assistant，等待全部结果
  -> tool_completed / tool_failed：按原始 tool_call_id 精确归入待提交组
  -> 校验调用 ID 非空且唯一、每个调用恰好一个结果、无未知 ID
  -> 全部配齐：同一短事务写入 assistant + 按原调用顺序排列的全部 tool，分配稳定 sequence
  -> 下一轮 begin 命令只按 sequence 读取 chat_messages
```

- `tool_failed` 属于真实完整工具结果，正常参与配对；`tool_started` 不算结果。
- 配对严格依据原始 `tool_call_id`，不按工具名或到达顺序猜测，也不补造或省略缺失调用。
- 无效、重复或冲突结果按协议错误处理，跳过该组提交。用户输入在受理时作为独立完整消息提交。

## 中断边界

- 取消与组提交在同一串行边界协调：当前事件若已进入临界区且使整组配齐，会先完成整组事务；取消事务提交后，后续事件直接丢弃，不再写入。
- 事务失败整组回滚，不会留下单独 assistant 或部分 tool 行。
- 示例：assistant 调用 A、B，仅收到 A 即被取消 -> assistant、A、B 整组都不写入 `chat_messages`，也不补造 B 的中断结果；此前已提交的用户消息和完整组保留。
- 过程事件不落库，取消后自然消失；暂存配对数据在取消、失败或流关闭时丢弃；进程退出前未提交的组不属于稳定历史。
- `chat_messages` 是中断后重建模型上下文的唯一持久化来源，收尾阶段只更新轮次状态，不重复写已提交的 assistant。

## 跨轮读取与提交顺序

```text
旧轮最后一次合法组提交 -> 本地取消事务提交 -> 新轮保存用户消息并读取 chat_messages 快照 -> 锁外执行
```

- 新轮在旧轮提交完取消终态后再读取历史，避免读到旧轮在途写入。
- `sequence` 在同一写事务中为整组分配并插入；唯一索引兜底防重，事务边界负责原子性。
- 旧执行体始终校验自身 `turn_id`，取消后即使后台仍在计算也不会补写。完整交接流程见 [DESIGN.md](../DESIGN.md)。
