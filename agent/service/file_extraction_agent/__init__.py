"""文档问答包：workspace 与完整历史 → stream_completion → 单轮事件。

schemas 定义输入契约，core 执行模型/工具循环。调用方持有并关闭异步生成器，
取消沿消费 Task 传播；本包不管理 session、活动 ID 注册表或数据库。
"""
