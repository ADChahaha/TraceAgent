# Backend API

`POST /chat/completion` 创建轮次，`GET /resume` 恢复页面及观察流，`POST /cancel` 取消指定轮次。前两个接口返回 `text/event-stream`，先发快照再发增量；浏览器断开只取消订阅，执行仍由 backend 持有。

## 目录

| 主题 | 文档 | 内容 |
| --- | --- | --- |
| 会话、提交与取消 | [api/sessions-and-completion.md](api/sessions-and-completion.md) | `GET /chat/sessions`、`POST /chat/completion`、`POST /cancel` 与失败边界 |
| 文件与文档读取 | [api/documents-and-files.md](api/documents-and-files.md) | `/blocks`、`/files/{resource_id}`、`/documents`、`/documents/full`、`/documents/content` |
| 恢复与 SSE | [api/resume-and-sse.md](api/resume-and-sse.md) | `GET /resume`、`session.snapshot` / `session.event` 格式与连接生命周期 |

相关：[DESIGN.md](DESIGN.md) / [SESSION_MANAGER.md](SESSION_MANAGER.md) / [table.md](table.md)
