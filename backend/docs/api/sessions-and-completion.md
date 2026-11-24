# 会话列表、问答提交、取消与边界

返回 [Backend API](../API.md)。

## `GET /chat/sessions?limit=100`

- 从数据库按 `updated_at`、`created_at` 与插入顺序倒序返回最近会话：
  `{"sessions":[{"id":"...","status":"ready","active_turn_id":null,"created_at":"...","updated_at":"..."}]}`
- `limit` 默认 100，允许 1-200，越界返回 422。不依赖浏览器缓存，也不加载会话执行器；打开具体会话使用 `/resume`。

## `POST /chat/completion`

JSON 请求示例：

```json
{"content":"总结文档","session_id":"已有会话 ID","run_options":{"tool_execution_timeout":120}}
```

- `content` 必填且不可为空白；省略 `session_id` 创建新会话，传入已有 `session_id` 创建下一轮。每次 POST 均按新提交处理，拿到 `session_id` 后断线改用 `GET /resume` 恢复。
- `run_options` 当前仅支持正的有限数 `tool_execution_timeout`。
- 文件上传支持 `multipart/form-data`（文本字段同上，`run_options` 为 JSON 文本；`file`/`files` 可重复，支持 PDF/DOCX，默认最多 20 个文件、总计 32 MiB）。
- 上传或删除走 document service 的 `PrepareResources`，成功后替换会话资源引用，有新文件的 queued turn 随后调用 agent service 的 `ChatCompletion`。失败会话需上传新文件重试；同一 session 有活跃轮时新提交冲突。
- 返回 `text/event-stream`，首帧快照含 `session_id`、`state.active_turn_id` 与 `state.turns`。

## `POST /cancel`

请求与响应示例：

```json
{"session_id":"s1","turn_id":"t1"}
```

```json
{"session_id":"s1","turn_id":"t1","status":"cancelled"}
```

- 先提交本地终态再取消对应 gRPC call；`turn_id` 必填以防旧页面取消新轮。
- 已终结 turn 返回原终态（幂等）。资源准备中取消会终止准备并将 session 标为 `failed`，后续需上传新文件。
- 只操作已加载会话；会话缺失或空闲已回收返回 404，不触发冷加载。

## 失败边界与辅助端点

- SSE 建立前输入错误、会话缺失、活跃轮冲突返回 HTTP 错误；上传总内容超限返回 413。执行开始后的 agent 错误经 `turn.failed` 呈现。
- 数据库事务失败停止对应 manager 并断开订阅；历史读取失败或快照超预算（默认 32 MiB，尚无分页）不发送残缺快照。
- backend 重启后遗留轮次标为 `failed`/`backend_restarted`，`resume` 不自动重做工具。
- 保留 `GET /healthz` 与 `GET /capabilities`；旧 `/qa/tasks` 已移除。当前单进程、单用户运行，无租户鉴权；agent 与 document service 可独立或跨主机部署。
