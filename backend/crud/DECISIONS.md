# backend/crud 关键决策

归属 [Backend 设计](../docs/DESIGN.md) 与 [Backend 数据表](../docs/table.md)，记录持久化与事务边界的长期取舍。

## 1. 事务提交权统一收口在 `crud.transaction()`

- 决定：所有 CRUD 写函数只执行 SQL 语句、绝不自行提交，也移除 `commit` 参数；提交与回滚统一由 `crud.transaction()`（`BEGIN IMMEDIATE`）控制；service 层不直接写 SQL。
- 原因：用代码结构强制保证多条关联写入（如建轮 + 写用户消息、整组工具消息提交、资源替换）同生共死，杜绝半提交状态。
- 排除：在写函数上保留 `commit=True/False` 参数由调用方各自决定何时提交。

## 2. `chat_messages` 只存配齐的稳定模型历史，禁止孤儿工具事件且不迁移旧 `qa_*` 表

- 决定：带工具调用的 assistant 消息与全部对应 `call_id` 工具结果在配齐后同事务提交，取消或中断时直接丢弃未配齐组且不补造伪结果；对称地，严禁将缺少前置 `assistant.tool_calls` 对应的孤儿或展示性工具事件写入 `chat_messages`（所有 `tool_completed`/`tool_failed` 须携带非空 `tool_call_id` 并唯一匹配待提交组）；初始化仅维护 `chat_*` 四张表，不迁移也不删除旧 `qa_*` 表。
- 原因：确保下一轮传给上游模型（如 Responses API）的历史严格满足 `tool_call` 与 `tool_result` 一一配对，杜绝孤儿 `function_call_output` 触发上游报错，同时避免旧表迁移拖累单用户本地库初始化。
- 排除：写入半截工具调用或补造伪工具结果；为孤儿/展示性工具失败事件合成假 `assistant.tool_calls` 或伪造 `call_id`；在启动阶段自动迁移旧版 `qa_*` 表。

## 3. 轮次终态收口统一依赖条件 `UPDATE` 防止过期读覆写

- 决定：轮次正常结束、主动取消与后台故障收口统一使用 `crud.update_turn_status_if_current`，在 `UPDATE chat_turns` 的 `WHERE` 条件中限定 `status IN ('queued', 'in_progress', 'cancelling')` 并检查 `rowcount`，未命中时返回 `None` 而不覆写已有终态。
- 原因：多路径收口存在并发竞态窗口，仅靠前置 `SELECT` 再无条件 `UPDATE` 会因过期读覆写已落库终态。
- 排除：先 `SELECT` 判断状态再执行无条件 `UPDATE chat_turns`。
