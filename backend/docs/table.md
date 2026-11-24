# Backend 数据表

持久化只有四张表：`chat_sessions`、`chat_resources`、`chat_turns`、`chat_messages`。过程事件（`delta`、`tool_started` 等）只存在于内存和订阅队列，不落库；页面恢复由 `chat_messages` 加 `chat_turns` 渲染历史轮，再合并当前轮内存副本。

- `chat_messages` 只保存可完整回传模型的稳定历史：普通消息单条提交，带工具调用的 assistant 与全部对应 tool 结果配齐后同事务提交，中断只丢弃未提交组。
- schema、CRUD 与 `SessionManager` 统一使用 `chat_*` 和 `session_id`；初始化不迁移也不删除旧 `qa_*` 表。
- CRUD 写函数只执行语句、永不自行提交，事务提交边界统一在 `crud.transaction()`。

## 目录

| 主题 | 文档 | 内容 |
| --- | --- | --- |
| 表结构与约束 | [table/schemas.md](table/schemas.md) | `chat_sessions`、`chat_resources`、`chat_turns`、`chat_messages` 字段与约束 |
| 配对与中断顺序 | [table/message-pairing.md](table/message-pairing.md) | 工具组原子配对、取消中断边界与跨轮读写串行顺序 |

相关：[DESIGN.md](DESIGN.md) / [SESSION_MANAGER.md](SESSION_MANAGER.md)
