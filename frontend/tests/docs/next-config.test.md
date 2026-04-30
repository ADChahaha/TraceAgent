# `next-config.test.ts`

## 基本实现思路

这个测试固定 Next.js 运行配置里和上传链路有关的代理体积限制。前端上传 PDF 时走的链路是：

```text
浏览器 multipart FormData
  -> /api/backend/tasks
  -> Next route handler 读取并转发 multipart body
  -> backend POST /tasks
```

如果 Next 代理层默认限制过小，2MB 以上的真实 PDF 会在到达 backend 前失败，页面只能看到 backend unavailable。

## 测什么

- `next.config.ts` 必须把 `experimental.proxyClientMaxBodySize` 配成 `10mb`。

## 每个函数在干什么

`允许前端代理转发 10MB 内的 PDF multipart 上传`

- 直接读取 `next.config.ts` 导出的配置对象。
- 检查 `experimental.proxyClientMaxBodySize` 是 `10mb`，确保科研作品这类 2MB 级 PDF 能经过前端代理上传。

## 怎么跑

```bash
pnpm test next-config.test.ts
```
