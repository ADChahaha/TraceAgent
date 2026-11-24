# Backend 数据访问、事务与生命周期

本页属 [Backend 设计](../DESIGN.md)，说明 CRUD 事务边界、四表模型、Manager 回收与故障收口规则。

## 数据访问边界

事务入口 `transaction()` 和业务 SQL 统一放在 `crud/crud.py`；service 通过 `with crud.transaction(db)` 将相关操作组合为原子提交，`core/db.py` 负责连接与数据库初始化：

```text
Registry.start -> list_sessions_needing_recovery / list_unfinished_turns -> 遗留轮次收口（error 写入 chat_turns）
Manager 创建或提交消息组 -> get_next_message_sequence -> 同事务插入完整消息
Manager 替换资源 -> delete_resources -> 同事务插入新资源
History.build_snapshot -> list_turns + list_messages -> 按 turn 分组渲染展示
```

- 过程事件不落库：事件只更新内存 `TurnView` 并广播订阅，页面恢复从 `chat_messages` 与 `chat_turns` 渲染。
- CRUD 不捕获数据库异常，也不自行提交，提交权归 `transaction()` 边界持有者，提交后才更新投影与广播。

## 四张表与消息配对

- 四张表为 `chat_sessions`、`chat_resources`、`chat_turns`、`chat_messages`，初始化不迁移旧 `qa_*` 数据（字段与约束见 [table.md](../table.md)）。
- 单个命令的写入在同一工作线程、同一事务完成。
- `chat_messages` 只保存完整模型历史：工具组按原始 `call_id` 配齐实际结果后原子提交；取消丢弃未配齐组。

## Manager 回收、故障收口与部署边界

- manager 只缓存当前 turn，终结后释放；SSE 在捕获的活跃轮终结时关闭，空闲会话仅发送一次快照。
- 无活跃轮、执行句柄、订阅及待处理命令时才回收 manager：entry 先从 `READY` 置 `CLOSING`，锁外关闭后移除，期间该 session 请求收到冲突。
- `cancel` 只操作已加载 manager，空闲已回收会话返回 404；backend 重启将遗留活跃轮标为 `failed`/`backend_restarted`，不重新执行 agent。
- 数据库事务失败会回滚并将 manager 标记损坏、取消执行、清空执行态与缓存认领、补发挂起的 cancel、关闭订阅，并尽力将活跃轮收口为 `failed`（数据库仍不可用时交给重启收口）；损坏 manager 空闲后可被回收，重载即恢复，不支持在线原地重建。
- 当前部署使用单 backend 进程、单用户，无跨进程 owner 协调和租户鉴权；旧 task 路由已删除。
