# Backend API

POST /chat/completion 创建轮次；GET /resume 恢复页面及观察流；POST /cancel 取消指定轮次。前两个接口先发送快照，再发送增量。断开只取消订阅，执行由 backend 持有。

## POST /chat/completion

```json
{"content":"总结文档","session_id":"已有会话 ID","run_options":{"tool_execution_timeout":120}}
```

content 必填且不可为空白；省略 session_id 创建会话，传入已有 session_id 则创建下一轮。每次 POST 都按新提交处理；拿到 session_id 后断线使用 GET /resume 恢复。

run_options 当前只支持正的有限数 tool_execution_timeout。上传使用 multipart/form-data，文本字段同上，run_options 为 JSON 文本；file 或 files 字段可重复，支持 PDF/DOCX，默认最多 20 个文件、总内容 32 MiB。

文件上传或删除走 document service 的 `PrepareResources`，成功后 backend 替换会话资源引用；有新文件的 queued turn 随后调用 agent service 的 `ChatCompletion`。失败会话需上传新文件重试。同一 session 已有活跃轮时新提交冲突。

## GET /chat/sessions/{session_id}/blocks?key=...

按引用 key 返回段落原文，供前端回溯答案中的证据链接（如 `[1](documents/0001-contract/0001-section/0001-block.md)`）：

```json
{"key":"documents/0001-contract/0001-section/0001-block.md","text":"付款期限为三十天。","found":true}
```

key 是 document service 发布的文档归档内的 `documents/...` 路径。bucket 取自本会话的 documents 引用，key 跨会话不可达；key 不在归档内或会话没有归档时返回 404。会话缺失或空闲已回收同样 404。

返回 text/event-stream，从快照取得 session_id、state.active_turn_id 和 state.turns。

## GET /resume?session_id=...

manager 捕获当前轮副本和已存在轮次列表并登记订阅，请求侧读取 chat_messages 与 chat_turns 渲染历史轮；查询期间的新事件排队。先合并发送快照，再消费增量。不会创建新 turn 或重新调用 agent。

无 after_seq、Last-Event-ID 或 SSE id 协议。前端保存 session_id；收到快照时替换已有会话展示。

## SSE 格式

```text
event: session.snapshot
data: {"session_id":"s1","state":{"status":"running","active_turn_id":"t1","resources":[],"turns":[{"id":"t1","status":"in_progress","items":[],"error":null}]}}

event: session.event
data: {"turn_id":"t1","type":"model_message.delta","payload":{"message_id":"m1","delta":"你好"}}

```

items 包含用户消息、模型尝试、工具和重试状态。按消息或调用 ID 更新，model_message.done 的完整正文替换累计 delta。不同模型尝试不可拼接。

增量字段为 turn_id、type、payload，不暴露内部序号。常见类型为 turn.started、model_message.started/delta/done、tool_started/completed/failed、turn.completed/failed/cancelled。默认 15 秒无事件时发送注释心跳。

流在首帧捕获的活跃轮终结后关闭；没有活跃轮时仅发送快照。正常终态不需重连，意外断开后重新 GET /resume。多页面订阅独立，慢页面溢出只断开自身。

## POST /cancel

请求：

```json
{"session_id":"s1","turn_id":"t1"}
```

响应示例：

```json
{"session_id":"s1","turn_id":"t1","status":"cancelled"}
```

先提交本地终态，再取消对应 gRPC call。turn_id 必填，避免旧页面取消新轮。已终结的 turn 返回原终态，重复取消幂等。资源准备中取消会终止准备并将 session 标为 failed，后续需上传新文件。cancel 只操作已加载会话；会话不存在或空闲已被回收时返回 404，不触发冷加载。

## 失败与边界

SSE 建立前输入错误、会话缺失、活跃轮冲突返回 HTTP 错误；上传总内容超限为 413。执行后的 agent 错误通过 turn.failed 呈现。数据库事务失败会停止该 manager、断开订阅。历史读取失败或快照超过预算不发送残缺快照。

backend 重启后遗留轮次为 failed/backend_restarted，resume 不自动重做工具。历史快照默认 32 MiB 预算，尚无分页。

GET /healthz 和 GET /capabilities 保留。旧 /qa/tasks 已移除。当前 backend 单进程、单用户使用，尚无租户鉴权；agent service 与 document service 可独立进程或跨主机部署。
