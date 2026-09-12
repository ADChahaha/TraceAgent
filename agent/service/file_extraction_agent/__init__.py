"""文档问答包：普通请求 → application 预检与装配 → core 执行 → 类型化业务事件。

application.stream_completion 提供完整业务入口，schemas 定义输入和事件契约。
路由仅进行协议适配；调用方关闭异步流时，取消逐层传播并清理工具进程。
"""
