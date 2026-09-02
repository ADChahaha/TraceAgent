"""
agent 核心机制包边界。

职责：

- 承载运行状态（GraphState）、agent loop、模型工厂、确定性 tools 和文档文件树。
- 作为 manager.py 之后的内部执行空间。
- 允许内部对象随实现演进调整，不作为外部稳定 API。

边界：

- 不直接作为调用方入口。
- 不访问数据库、backend storage 或人工审核。
- 不重新承担 manager.prepare_completion_state 已经完成的入口契约校验。
"""
