# Backend API

`POST /chat/completion` 创建轮次，`GET /resume` 恢复页面及观察流，`POST /cancel` 取消指定轮次。前两个接口返回 `text/event-stream`，先发快照再发增量；浏览器断开只取消订阅，执行仍由 backend 持有。

## 主题索引（按需打开）

| 主题 | 子文档 | 涵盖内容 |
| --- | --- | --- |
| 会话列表、问答提交与取消 | [api/sessions-and-completion.md](api/sessions-and-completion.md) | `GET /chat/sessions`、`POST /chat/completion`（JSON/multipart）、`POST /cancel`、探活与失败边界 |
| 文件下载与文档内容读取 | [api/documents-and-files.md](api/documents-and-files.md) | `/blocks`、`/files/{resource_id}`、`/documents`、`/documents/full`、`/documents/content` |
| 页面恢复与 SSE 协议 | [api/resume-and-sse.md](api/resume-and-sse.md) | `GET /resume`、`session.snapshot` 与 `session.event` 格式、心跳与连接生命周期 |

## 相关入口

- Backend 顶层设计：[DESIGN.md](DESIGN.md) / SessionManager 架构：[SESSION_MANAGER.md](SESSION_MANAGER.md) / 数据表：[table.md](table.md)
