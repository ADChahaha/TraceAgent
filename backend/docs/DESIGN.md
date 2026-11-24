# Backend 设计

backend 管理多轮 session、稳定模型消息和页面恢复，通过独立 document service 准备资源、通过独立 agent service 执行单次 turn。每个已加载 session 有唯一 `SessionManager`，串行处理创建、取消、事件和订阅；网络等待位于独立 `TurnRuntime`。浏览器断开只释放订阅。

`GET /chat/sessions` 从数据库按更新时间读取最近会话，默认 100 条（`limit` 范围 1-200）；读取不加载 manager、不创建会话，所有连接到同一 backend 的浏览器共享列表。

## 主题索引（按需打开）

| 主题 | 子文档 | 涵盖内容 |
| --- | --- | --- |
| 调用关系与模块边界 | [design/call-flow-and-modules.md](design/call-flow-and-modules.md) | completion/resume/文件读取/cancel 调用链、10 个核心模块职责与 Registry 状态机 |
| 数据访问与生命周期 | [design/data-and-lifecycle.md](design/data-and-lifecycle.md) | CRUD 事务边界、四张表角色、消息配对、manager 回收、损坏收口与单进程边界 |

## 专题与接口入口

- 架构细节与并发所有权：[SESSION_MANAGER.md](SESSION_MANAGER.md)
- HTTP / SSE 接口规范：[API.md](API.md)
- 数据表与消息配对：[table.md](table.md)
- 流程图：[flowchart.md](flowchart.md)（注：Agent 合并方案已取消，旧草案不再使用）
