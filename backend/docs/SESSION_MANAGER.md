# SessionManager、gRPC 执行与页面恢复

本文记录已落地的 backend 架构，分层对齐公开 Codex（`53c542d9`）的 core/app-server 边界：每个已加载 session 对应唯一 manager（类比 app-server `ThreadState`），只拥有 session 级状态和命令编排；每轮一个 `TurnRuntime`（类比 core 的 Session+turn 循环）自治执行，拥有轮内全部状态。历史从数据库恢复，过程事件不落库。

## 目录

| 主题 | 文档 | 内容 |
| --- | --- | --- |
| 所有权与建轮 | [session_manager/ownership-and-create.md](session_manager/ownership-and-create.md) | manager/runtime 所有权、8 文件职责、`exclusive-create` 与 `runtime.begin` |
| 资源与串行事务 | [session_manager/resources-and-concurrency.md](session_manager/resources-and-concurrency.md) | 上传/删除与读路径、两层串行化、`manager.fail()`、`cancel` 与 CRUD 事务 |
| 上下文与 Resume | [session_manager/context-and-resume.md](session_manager/context-and-resume.md) | 消息配对提交、`TurnView`/`Subscription`、`GET /resume` 冻结轮次一致性 |
| 取消容量与参考 | [session_manager/lifecycle-and-limits.md](session_manager/lifecycle-and-limits.md) | 取消/回收/重启收口、`BackendSettings` 默认阈值、测试覆盖与 Codex 参考 |

相关：[DESIGN.md](DESIGN.md) / [API.md](API.md) / [table.md](table.md)
