# error-messages.test.ts

验证 `frontend/src/lib/error-messages.ts` 的前端错误兜底与 `Conversation` 渲染行为：

- 验证 `backend_restarted`、`storage_failure`、`backend unavailable`、`Failed to fetch` 与 `Stream interrupted` 映射为清晰可读的英文文案。
- 验证旧会话历史或异常通道漏出的 `gRPC`、`ipv4:127.0.0.1`、`socksio`、`<html>` 等技术报错串均被拦截并按上下文降级为友好英文说明，不向界面暴露底层细节。
- 验证已脱敏的简洁英文业务提示（如 `Upload failed`、`Only PDF and DOCX files are supported.`）原样保留。
- 验证 `Conversation` 展示失败轮次时自动对 `turn.error` 做用户态格式化。

运行：`pnpm --dir frontend exec jest tests/error-messages.test.ts --runInBand`。
