# test_empty_model_reply.py

- `test_empty_terminal_reply_is_a_retryable_failure`：模拟带合法 stop 信号但正文为空、纯空白、空白文本块或只有隐藏推理的模型流，验证调用层返回可重试失败，不能发出可持久化的完成消息。
- `test_empty_reply_is_not_added_to_retry_history`：通过真实图执行一次空白响应及一次正常回答，验证图重试同一请求、下一次输入和最终历史都不包含空白 assistant 消息，避免下一轮 DocumentQaMessage 校验失败。
