# test_session_title.md

对应测试文件：`tests/test_session_title.py`

## 验证内容

验证旧 SQLite 数据库自动补齐 `chat_sessions.title` 列、首轮问答异步触发模型标题总结与落库、标题模型失败/超时时的安全降级，以及旧会话列表与恢复快照的兜底标题派生。

## 测试函数

- `test_initialize_database_migrates_legacy_chat_sessions_without_title_column`：构造仅 5 列的旧库并幂等执行 `initialize_database`，验证补齐 `title` 列且历史数据完好。
- `test_first_turn_generates_title_async_and_second_turn_does_not_overwrite`：验证上传文件后未提问先回退文件名、首轮提问后异步调用 `generate_title` 落库并反映在 `/chat/sessions` 与 `/resume`，且第二轮不重复生成覆盖。
- `test_title_failure_and_timeout_do_not_block_completion_and_fall_back_safely`：分别模拟标题模型抛错与超时，验证主问答照常完成并落库首条问题摘要作为安全兜底标题。
- `test_legacy_sessions_without_title_derive_readable_fallbacks_never_uuid`：验证空会话、仅文件会话、仅历史消息会话在 `title` 为空时依次按首问、首个文件名与 `Untitled workspace` 派生，绝不返回 UUID。
