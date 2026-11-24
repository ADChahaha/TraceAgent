# 流式传输、订阅生命周期与状态合并

返回 [Frontend 设计](../DESIGN.md)。

## 请求与 SSE 解析

- `api.ts` 分离封装 JSON 接口与流接口：提问用带 JSON 体的 `fetch POST`，恢复用 `fetch GET`（不用仅支持 GET 的 `EventSource`）；非成功状态转为 `ApiError`，流接口额外校验 `text/event-stream`。
- `session-stream.ts` 使用 `TextDecoder` 增量解码 UTF-8 并缓存跨网络分块的 SSE 行，支持 LF/CRLF、多行 `data` 与心跳注释，仅分发 `session.snapshot` 和 `session.event`；无效 JSON 报错，回调完成或 `AbortSignal` 取消时立即释放 reader。

## 页面订阅生命周期（`use-session.ts`）

```text
进入页面 -> GET /resume -> snapshot 整份替换投影
session.event -> session-state 按 turn/message/tool ID 合并更新
终态或空闲快照 -> 关闭订阅
活跃流提前结束 / 网络错误 -> 退避后仅 GET /resume（不重发 POST）
卸载 / 切换会话 -> abort 旧订阅；连接代次拒绝旧请求迟到结果
```

- 重连始终重新读快照，不重放旧增量、不自动重发 POST，避免产生重复轮次。
- 不可恢复参数错误或 404 显示错误和手动恢复入口；运行中允许编辑下一轮草稿，待提交问题先展示本地占位，收到快照后由后端消息替换。

## 状态合并与取消（`session-state.ts`）

合并语义与 backend `TurnView` 严格对齐：

- `snapshot` 原样替换历史与当前轮。
- `model_message.delta` 按 `message_id` 追加；`done` 用完整 `content` 替换，不再重复拼接。
- `retry` 标记原尝试失败，新 `message_id` 独立展示。
- 工具按 `tool_call_id` 更新同一条目，连续工具在 UI 折叠为过程组。
- `turn.completed`/`failed`/`cancelled` 结束轮次并将未完成条目标为 `interrupted`；已结束轮次忽略迟到事件，旧轮终态不会清空新轮 ID。
- 主动取消调用 `POST /cancel` 同时传 `session_id` 与 `active_turn_id`，成功终态响应立即更新投影并释放订阅；关闭页面本身只断开订阅，不发取消。
