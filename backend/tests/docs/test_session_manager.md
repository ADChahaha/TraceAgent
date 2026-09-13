# test_session_manager.py

临时 SQLite → SessionRegistry/SessionManager → 可控假 agent 事件流 → 比对持久化、当前轮快照和订阅结果。使用事件与锁的握手固定竞争顺序。

- `test_detach_keeps_execution_and_resume_merges_history`：关闭订阅不取消执行；恢复合并历史与当前轮，下一轮只使用稳定模型消息。
- `test_attach_boundary_survives_completion_and_next_turn`：捕获恢复边界后发生完成和新轮启动，首帧与后续流不重复、不漏事件。
- `test_cancel_rejects_late_event_and_does_not_cancel_new_turn`：旧轮取消后丢弃迟到写入，重复取消旧轮不伤害新轮。
- `test_concurrent_create_has_one_active_turn_and_one_manager`：并发获取返回同一 manager，重复启动活跃轮拒绝。
- `test_completion_has_no_request_deduplication`：接口拒绝已删除的 request_id；相同问题独立提交创建不同会话，创建事件不再保存去重元数据。
- `test_cancelled_creation_aborts_ownership_and_retry`：创建权持有期间其他 complete/get 冲突；请求被取消后创建权回滚、未产生轮次，下一次请求可重新创建。
- `test_tool_group_is_atomic_and_next_history_uses_original_ids`：同名工具按原调用 ID 配对，乱序成功/失败结果齐备后整组提交。
- `test_tool_write_failure_rolls_back_group_and_process_event`：注入真实 SQLite 写入失败，assistant/tool 组及过程事件均回滚并关闭异常管理器订阅。
- `test_idle_unload_and_cold_resume_do_not_keep_history_in_manager`：无订阅的活跃任务不卸载，空闲后冷恢复可查询历史且不常驻历史缓存。
- `test_startup_marks_orphan_execution_failed_without_restarting_agent`：启动时收口遗留活跃轮次，不重放模型执行。
- `test_retry_marks_failed_attempt_and_terminal_clears_retry_state`：重试标记原模型尝试失败，终态不会留下仍在重试的展示项。
- `test_closing_entry_rejects_get_until_removed`：回收关闭期间 entry 为 CLOSING，get/complete 冲突；关闭完成后移除，可重新加载新 manager。
- `test_get_unknown_session_raises_not_found`：Registry.get 对未加载会话返回 NotFound，不触发冷加载。
- `test_missing_tool_result_does_not_fabricate_history`：缺少真实工具结果时拒绝入库，不补造失败正文。
- `test_registry_can_load_after_cleanup`：Registry 清理资源后仍可重新加载已有会话，不通过服务关闭标志拒绝访问。
