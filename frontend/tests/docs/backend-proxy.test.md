# backend-proxy.test.ts

Next route handler 透明转发浏览器请求，测试在 Node 环境使用真实 Request/Response。

- 会把 multipart 表单转发到 backend 目标路径：保持 boundary、二进制上传体和请求取消信号，移除不适合转发的 expect 头。
- 会保留 backend 错误状态和 detail 响应：业务错误不转成成功。
- backend 不可达时会返回明确的 502 detail：错误入口稳定。
- 会把 text/event-stream 响应作为流转发，不先读成完整文本：保留实时消费能力。
- 原文件下载按二进制透传并保留文件名：包含无效 UTF-8 字节，验证不能经过 text 解码。
