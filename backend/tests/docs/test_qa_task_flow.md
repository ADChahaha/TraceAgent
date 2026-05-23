# test_qa_task_flow.py

这份测试覆盖 backend 破坏式重构后的 QA-only 任务流。旧的 `/tasks + task_spec + field extraction + result/trace/audit` API 不再是目标行为；backend 现在只负责多文档 QA 会话、消息、turn、事件续传和取消。

实现链路：

```text
POST /qa/tasks 上传 PDF
  -> route 读取 multipart files/file 和 metadata
  -> qa_task_service 先校验 PDF 类型并保存 qa_tasks
  -> 写入 task.created 事件
  -> 立刻返回 processing/document_processing task snapshot
  -> 后台线程调用 agent document_processor
  -> 保存 qa_documents，写入 document.processed 和 task.ready

POST /qa/tasks/{task_id}/inputs
  -> 校验 task 存在且没有 active turn
  -> 保存 user message 和 turn.created
  -> 立刻返回 queued turn snapshot
  -> 后台调用 agent POST /v1/document-qa/chat/completions
  -> 持久化 agent.event
  -> completion.completed/cancelled/failed 映射成 turn.completed/cancelled/failed
  -> 把最后一条非空 model_message 保存为 assistant message，供下一轮传给 agent

GET /qa/tasks/{task_id}/events?after_seq=n
  -> 从 qa_events 读取 seq > n 的事件并以 SSE 返回
  -> 当前没有 active turn 且已发完已有事件时关闭

GET /qa/tasks/{task_id}
  -> 返回 task summary
  -> 同时返回 qa_documents 的 document_id/filename/display_html
  -> 从最近的 source_indexed agent.event 提取 source_selectors，供前端 evidence review 定位原文

POST /qa/tasks/{task_id}/cancel
  -> 标记 active turn cancelling
  -> 如果已有 agent_completion_id，转发 agent cancel
  -> 写入 turn.cancel_requested 事件
```

## 测试函数

- `test_create_qa_task_processes_documents_without_task_spec`：验证创建 QA task 不再需要 `task_spec`，接口先返回 `processing/document_processing`，后台会调用 document_processor 保存文档，并且旧 `/tasks` route 已下线。
- `test_qa_input_runs_agent_completion_and_persists_events`：验证用户输入接口先返回 `queued`，后台会调用 document QA completion，持久化 user message、turn、agent model message 和 terminal event，且 evidence link 保留在 `model_message` 内容中。
- `test_qa_input_runs_agent_completion_and_persists_events`：同时验证现有 task detail 端点会返回 `documents[].display_html` 和 `source_selectors`，前端无需调用旧 replay 或新 review 端点即可打开 evidence 原文。
- `test_qa_second_input_sends_prior_messages_to_agent`：验证第二轮输入会把上一轮 user/assistant 消息一起传给 agent，backend 是多轮状态事实来源。
- `test_qa_task_rejects_new_input_while_turn_is_active`：验证同一个 QA task 同时只允许一个 active turn。
- `test_qa_cancel_active_turn_calls_agent_cancel`：验证 cancel 会标记 active turn、转发 agent cancel，并写入 `turn.cancel_requested` 事件。
