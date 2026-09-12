# test_session_primitives.py

真实 SQLite 验证跨 CRUD 原子回滚；事件输入 TurnView 后检查累积结果；向独立订阅队列写入事件验证背压隔离。

- `test_transaction_rolls_back_all_crud_writes`：通过 crud.transaction 进入事务，后续外键写入失败时，先前会话写入也回滚。
- `test_turn_view_done_replaces_deltas_and_keeps_attempts_separate`：done 替换正文，不重复追加，不合并不同模型尝试。
- `test_subscription_overflow_closes_only_slow_subscriber`：慢订阅溢出后明确关闭，不影响其他订阅。
- `test_runtime_cancel_before_first_step_cleans_up`：后台协程第一步前取消也报告收尾，重复取消不打断清理。
- `test_cancelled_subscription_wait_does_not_consume_an_event`：等待被心跳超时或请求取消打断时，事件要么已返回，要么保留在队列中。

- `test_services_delegate_sql_to_crud`：检查 services 不直接调用 SQL 执行方法，数据访问统一交给 CRUD。
