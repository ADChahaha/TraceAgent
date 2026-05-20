"""
内部实现包边界。

职责：

- 承载 graph、state、内部 schema、阶段 runner、prompt builder 和确定性 tools。
- 作为 processor.py 之后的内部执行空间。
- 允许内部对象随实现演进调整，不作为外部稳定 API。

边界：

- 不直接作为调用方入口。
- 不访问数据库、backend storage 或人工审核。
- 不重新承担 input_adapter.py 已经完成的入口契约校验。
"""
