# 稳定消息表测试

使用临时 SQLite 文件经正式 initialize_database 建表，再直接插入消息验证数据库约束；不接入事件消费或配对业务。

- `test_message_table_survives_reinitialization_and_orders_history`：重复初始化保留消息，按 sequence 稳定排序，外键有效。
- `test_message_table_rejects_invalid_rows`：拒绝非法角色、序号、组内位置、工具字段、JSON、跨 session/turn 关联、system 角色及空 turn_id。
- `test_message_table_rejects_duplicate_position`：轮内消息序号和组内位置不能重复。
- `test_message_sequence_unique_within_turn_not_across_turns`：per-turn seq——同一 turn 内序号唯一，不同 turn 可复用相同序号。
- `test_message_table_tool_ids_are_unique_within_group`：同组调用 ID 唯一，不同组允许复用。
- `test_message_group_transaction_rolls_back_on_write_failure`：组内第二行写入失败时，调用方事务回滚第一行；不代表配对业务已实现。
