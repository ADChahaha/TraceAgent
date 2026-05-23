"""
file_extraction_agent 包边界。

职责：

- 标识 document QA agent 的 Python 包根。
- 对外使用应优先经过 processor.create_completion_stream(...)、processor.cancel_completion(...) 和 schemas.py 中的稳定契约。
- 不承载业务实现、阶段编排、模型调用、工具调用、会话持久化或数据库访问。
- 不暴露 impl/ 下的内部阶段对象作为长期稳定 API。
"""
