# `backend-proxy.test.ts`

这组测试覆盖 Next route handler 对 backend 的透明代理。前端仍只访问 `/api/backend/*`，由代理把路径和 body 转发给 FastAPI。

## 测试链路

```text
浏览器请求 /api/backend/*
  -> forwardBackendRequest 解析 pathSegments
  -> 按 BACKEND_BASE_URL 拼出 backend URL
  -> multipart body 以原始 ArrayBuffer 透传
  -> application/json body 原样透传
  -> text/event-stream 直接返回 ReadableStream
  -> backend 状态码、content-type 和响应体返回给浏览器
```

## 测试函数

- `会把 multipart 表单转发到 backend 目标路径`：验证 `/api/backend/qa/tasks` 上传会被转发到 backend `/qa/tasks`，并保留 multipart boundary。
- `会保留 backend 错误状态和 detail 响应`：验证 `/qa/tasks/{task_id}/inputs` 返回 `422 detail` 时代理不会吞掉错误。
- `backend 不可达时会返回明确的 502 detail`：验证 backend 连接失败时返回稳定的 `backend unavailable`。
- `会把 text/event-stream 响应作为流转发，不先读成完整文本`：验证 `/qa/tasks/{task_id}/events` SSE 会被流式透传。
