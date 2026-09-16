# `test_agent_resource_integration.py`

验证 document service 和 agent service 通过 storage 与 `ResourceRef` 交接，而不是通过 Python 模块交接。

每个测试的 `session_id` fixture 提供独立会话 id，document service 按契约把资源发布进 `res_<session_id>` 桶。

- `test_qa_uses_prepared_path_without_rebuilding_or_deleting`：document service 生成资源后，agent 两轮问答复用同一对象集合。
- `test_qa_rejects_unmanaged_resource_path`：agent 拒绝缺失 documents/index 的资源引用。
- `test_qa_rejects_damaged_resource_without_rebuilding`：agent 拒绝损坏资源，且不尝试重建 document 资源。
