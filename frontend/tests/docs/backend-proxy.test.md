# `backend-proxy.test.ts`

这组测试覆盖 Next route handler 代理 backend 的基础行为，避免浏览器直接跨域访问 FastAPI。

## 测试链路

```text
浏览器请求 /api/backend/*
  -> forwardBackendRequest 解析目标 path
  -> 按 BACKEND_BASE_URL 组装 backend URL
  -> multipart 请求重新读取为 FormData 并转发
  -> backend 响应状态、content-type 和 body 原样返回给浏览器
```

## 测试函数

- `会把 multipart 表单转发到 backend 目标路径`：验证上传任务的 multipart 表单会被转发到 backend `/tasks`，并避免手动复用旧 boundary。
- `会保留 backend 错误状态和 detail 响应`：验证 backend 返回 `422` 和 `detail` 时，前端代理不会吞掉错误语义。
- `backend 不可达时会返回明确的 502 detail`：验证 backend 未启动或网络失败时，代理返回稳定的 `502` 和 `backend unavailable`，前端可以展示清晰错误。
