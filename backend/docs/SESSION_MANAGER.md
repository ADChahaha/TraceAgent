# SessionManager、gRPC 执行与页面恢复

本文记录已落地的 backend 架构，分层对齐公开 Codex（`53c542d9`）的 core/app-server 边界：每个已加载 session 对应唯一 manager（类比 app-server `ThreadState`），只拥有 session 级状态和命令编排；每轮一个 `TurnRuntime`（类比 core 的 Session+turn 循环）自治执行，拥有轮内全部状态。历史从数据库恢复，过程事件不落库。

## 主题索引（按需打开）

| 主题 | 子文档 | 涵盖内容 |
| --- | --- | --- |
| 所有权划分与创建轮次 | [session_manager/ownership-and-create.md](session_manager/ownership-and-create.md) | manager/runtime 所有权表、8 文件职责、`exclusive-create` 与 `runtime.begin` 建轮 |
| 资源串行与事务边界 | [session_manager/resources-and-concurrency.md](session_manager/resources-and-concurrency.md) | 文件上传/删除与读路径、两层串行化、`manager.fail()`、`cancel` 语义与 CRUD 事务 |
| 稳定上下文、订阅与 Resume | [session_manager/context-and-resume.md](session_manager/context-and-resume.md) | 消息配对提交、`TurnView`/`Subscription`、`GET /resume` 冻结轮次一致性与超时预算 |
| 取消卸载、容量与参考 | [session_manager/lifecycle-and-limits.md](session_manager/lifecycle-and-limits.md) | 取消/回收/重启收口、`BackendSettings` 默认阈值、行为测试与 Codex 参考锚点 |

## 相关入口

- Backend 顶层设计：[DESIGN.md](DESIGN.md) / 接口规范：[API.md](API.md) / 数据表：[table.md](table.md)
