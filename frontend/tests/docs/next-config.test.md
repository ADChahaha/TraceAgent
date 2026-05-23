# `next-config.test.ts`

这个测试固定 Next.js 代理上传体积配置。QA task 创建仍然通过前端代理上传 PDF，因此代理层不能在请求到达 backend 前截断真实文件。

## 测试链路

```text
浏览器 multipart FormData
  -> /api/backend/qa/tasks
  -> Next route handler 转发 multipart body
  -> backend POST /qa/tasks
```

## 测试函数

- `允许前端代理转发 10MB 内的 PDF multipart 上传`：验证 `next.config.ts` 的 `experimental.proxyClientMaxBodySize` 是 `10mb`。
