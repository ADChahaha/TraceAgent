# Frontend 设计

前端把 backend 的 session 快照作为对话事实来源，随后按 turn/message/tool ID 合并本次订阅的增量。浏览器通过 Next.js `/api/backend/*` 代理访问后端，不再调用已删除的 `/qa/tasks`，不再以全局 seq 或旧 replay 重建历史。页面地址保持 `/tasks/{session_id}`，路径 ID 即后端会话 ID。

```text
选择文件 -> POST /chat/sessions（首次）-> 串行 POST /chat/sessions/{id}/files
  -> 全部就绪后自动跳转 /tasks/{session_id} -> GET /resume 加载快照
  -> 提交问题 POST /chat/completion -> SSE 增量更新 -> 点击数字引用打开原文高亮
```

## 主题文档

- [上传与会话](design/uploads-and-sessions.md)：逐文件串行队列、删除与补传、自动跳转草稿交接、`workspace-list` 与轮询
- [流式与状态](design/streaming-and-state.md)：`api.ts`、`session-stream.ts`、`use-session.ts` 重连代次、`session-state.ts` 合并与取消
- [文档、布局与代理](design/documents-and-ui.md)：Sources/阅读视图、数字引用高亮、组件分工、响应式分栏、代理容量与测试

相关：[lib 决策](../src/lib/DECISIONS.md) / [components 决策](../src/components/DECISIONS.md) / [backend API](../../backend/docs/API.md) / [backend 设计](../../backend/docs/DESIGN.md) / [README.md](../../README.md)
