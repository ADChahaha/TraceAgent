# test_session_manager.py

临时 SQLite → SessionRegistry/SessionManager → 可控假 agent 事件流 → 比对持久化、runtime 状态和订阅结果。使用事件与锁的握手固定竞争顺序。分层：manager 只有 create/cancel/attach，turn 执行态在 TurnRuntime。

- `test_detach_keeps_execution_and_resume_merges_history`：关闭订阅不取消执行；恢复合并历史与当前轮，下一轮只使用稳定模型消息。
- `test_snapshot_renders_history_from_messages_without_events`：不经过事件路径、仅用 CRUD 构造的轮次和消息，快照按 chat_messages/chat_turns 渲染出用户、assistant（含工具调用列表）、成功与失败工具项及 turn 终态错误。
- `test_attach_snapshot_survives_completion_and_next_turn`：attach 冻结已存在轮次列表后发生完成和新轮启动，首帧不重复、新轮只经订阅送达。
- `test_cancel_rejects_late_event_and_does_not_cancel_new_turn`：旧轮取消后 runtime 丢弃迟到事件，重复取消旧轮不伤害新轮。
- `test_concurrent_create_has_one_active_turn_and_one_manager`：并发获取返回同一 manager，重复启动活跃轮拒绝。
- `test_completion_has_no_request_deduplication`：接口拒绝已删除的 request_id；相同问题独立提交创建不同会话，各自产生独立轮次。
- `test_manager_create_validates_content_and_run_options`：manager 的 create 入口校验空白 content、未知 run_options 字段和非正数工具超时，registry 不再承担业务校验。
- `test_cancelled_creation_aborts_ownership_and_retry`：创建权持有期间其他 get/get_or_create 冲突；请求被取消后创建权回滚、未产生轮次，下一次请求可重新创建。
- `test_cancelled_queued_create_recycles_subscription`：create 命令排队期间调用方取消，命令仍执行并创建轮次，无人接收的订阅被回收。
- `test_cancelled_create_during_handler_recycles_subscription`：begin 事务执行中调用方取消，同样不撤销命令且回收订阅。
- `test_failed_begin_returns_error_without_runtime_or_subscription`：runtime 的 begin 建轮事务失败把异常直接还给调用方，轮次和用户消息整体回滚，不残留订阅或活跃认领。
- `test_created_turn_snapshot_carries_user_message`：create 返回的首帧快照由 runtime 的 begin 事务提交后的视图渲染，携带用户消息和 in_progress 状态。
- `test_cancel_rejects_events_after_signal`：取消信号后 runtime 丢弃后续事件，不写库。
- `test_cancelled_caller_after_result_recycles_subscription`：handler 已写入结果、调用方恢复前被取消的窄窗口，订阅由同步守卫回收。
- `test_tool_group_is_atomic_and_next_history_uses_original_ids`：同名工具按原调用 ID 配对，乱序成功/失败结果齐备后整组提交（runtime 自治写库）。
- `test_tool_write_failure_rolls_back_group`：注入真实 SQLite 写入失败，assistant/tool 组整组回滚并关闭异常管理器订阅。
- `test_idle_unload_and_cold_resume_do_not_keep_history_in_manager`：无订阅的活跃任务不卸载，空闲后冷恢复可查询历史且不常驻历史缓存。
- `test_startup_marks_orphan_execution_failed_without_restarting_agent`：启动时收口遗留活跃轮次，不重放模型执行。
- `test_retry_marks_failed_attempt_and_terminal_clears_retry_state`：重试标记原模型尝试失败，终态不会留下仍在重试的展示项。
- `test_closing_entry_rejects_get_until_removed`：回收关闭期间 entry 为 CLOSING，get/get_or_create 冲突；关闭完成后移除，可重新加载新 manager。
- `test_get_unknown_session_raises_not_found`：Registry.get 对未加载会话返回 NotFound，不触发冷加载。
- `test_missing_tool_result_does_not_fabricate_history`：缺少真实工具结果时拒绝入库，不补造失败正文。
- `test_registry_can_load_after_cleanup`：Registry 清理资源后仍可重新加载已有会话，不通过服务关闭标志拒绝访问。
