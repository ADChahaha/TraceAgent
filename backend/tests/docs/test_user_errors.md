# test_user_errors.py

验证 `backend/services/user_errors.py` 接入 HTTP 路由与 `TurnRuntime` 后的对外错误脱敏契约：

- `test_upload_http_errors_hide_internal_details_and_log_raw_error`：模拟文档服务 `UNAVAILABLE`、`DEADLINE_EXCEEDED`、`INVALID_ARGUMENT` 与 `INTERNAL` 失败，验证 502 响应返回对应清晰英文提示、不含 `gRPC` / `ipv4:` / `127.0.0.1` / `Traceback` 等内部细节，且原始错误保留在服务端日志中。
- `test_http_validation_and_not_found_return_clear_english_messages`：验证非法文件类型、非法请求体与缺失会话均返回清晰英文提示，不暴露 Pydantic 原始栈或内部中文文案。
- `test_turn_failure_sanitizes_sse_and_snapshot_while_logging_details`：模拟代理/依赖初始化异常、问答服务不可达、429 限流、上游超时及流未发终态提前中断，验证 SSE `turn.failed` 与 `/resume` 快照中的 `turn.error` 均为具体英文提示且不泄露内部细节，同时服务端日志记录原始异常。

运行：`NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost conda run -n agent-gate python -m pytest backend/tests/test_user_errors.py -q`。
