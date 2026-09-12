# test_session_manager.py

临时 SQLite → SessionRegistry/SessionManager → 可控假 agent 事件流 → 比对持久化、当前轮快照和订阅结果。使用队列握手固定竞争顺序。

- `test_detach_keeps_execution_and_resume_merges_history`：关闭订阅不取消执行；恢复合并历史与当前轮，下一轮只使用稳定模型消息。
- `test_attach_boundary_survives_completion_and_next_turn`：捕获恢复边界后发生完成和新轮启动，首帧与后续流不重复、不漏事件。
- `test_cancel_rejects_late_event_and_does_not_cancel_new_turn`：旧轮取消后丢弃迟到写入，重复取消旧轮不伤害新轮。
- `test_concurrent_create_has_one_active_turn_and_one_manager`：并发获取返回同一 manager，重复启动活跃轮拒绝。
- `test_request_id_retry_reuses_session_after_response_loss`：初次响应丢失后凭请求 ID 找回原会话与轮次，冲突内容拒绝。
- `test_cancelled_request_stops_acceptance`：受理逻辑等待创建锁时显式取消请求协程，确认等待被取消且没有创建轮次；不依赖私有转发方法。
- `test_tool_group_is_atomic_and_next_history_uses_original_ids`：同名工具按原调用 ID 配对，乱序成功/失败结果齐备后整组提交。
- `test_tool_write_failure_rolls_back_group_and_process_event`：注入真实 SQLite 写入失败，assistant/tool 组及过程事件均回滚并关闭异常管理器订阅。
- `test_idle_unload_and_cold_resume_do_not_keep_history_in_manager`：无订阅的活跃任务不卸载，空闲后冷恢复可查询历史且不常驻历史缓存。
- `test_startup_marks_orphan_execution_failed_without_restarting_agent`：启动时收口遗留活跃轮次，不重放模型执行。
- `test_retry_marks_failed_attempt_and_terminal_clears_retry_state`：重试标记原模型尝试失败，终态不会留下仍在重试的展示项。
- `test_cancelled_cold_load_still_registers_owned_manager`：冷加载请求断开后，Registry 仍接管加载结果，不遗留无注册实例。
- `test_missing_tool_result_does_not_fabricate_history`：缺少真实工具结果时拒绝入库，不补造失败正文。
