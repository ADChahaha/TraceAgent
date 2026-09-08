# 流式模型与重试测试

通过真实 BaseChatModel 回调驱动 LangGraph，使用 Event 控制模型输出和退避，不请求外部模型。

- `test_native_messages_arrive_before_model_finishes`：第二块被阻塞时先收到第一块，验证消息 ID、完整结果和无重复文本。
- `test_graph_retries_same_model_five_times_and_reports_before_wait`：固定随机源验证 0.5 秒起步的指数抖动，事件等待时间与实际等待一致；同配置五次、消息 ID 独立。
- `test_model_failure_preserves_valid_retry_after`：保留限流响应中的毫秒、秒数或 HTTP 日期，校验 120 秒边界及无效/非有限值。
- `test_retry_backoff_caps_base_and_honors_server_delay`：指数基数以 8 秒封顶，服务端有效等待不叠加随机抖动。
- `test_server_retry_delay_reaches_event_and_wait`：真实限流异常通过单次调用、图状态和事件包装后，30 秒指示同时进入重试事件及等待，仍只请求五次。
- `test_single_model_call_returns_failure_without_retry`：单次调用只返回失败对象，重试由图负责。
- `test_cancel_model_closes_stream_without_retry`：取消关闭模型流并传播 CancelledError，不发生重试。
- `test_runtime_cancel_during_retry_wait_stops_next_attempt`：业务取消打断退避，关闭等待并只输出取消终态。
- `test_retry_success_keeps_failed_partial_text_out_of_history`：第五次成功，前四次局部文本不进入历史，重试状态归零。
- `test_chatopenai_native_callback_and_http_stream_close`：真实 ChatOpenAI 和 SDK 消费受控 SSE 响应，验证原生增量及取消关闭 HTTP 响应。
