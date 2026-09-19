# test_session_list.py

- `test_sessions_are_visible_to_another_client_after_restart`：第一个 HTTP 客户端创建会话，关闭应用后第二个客户端连接相同 SQLite，仍能列出会话并恢复；同时验证 limit 上下界拒绝非法值，避免把可见性绑定到浏览器或 manager 内存。
