"""问答核心：资源路径初始化工具 → 运行配置绑定执行器 → MessagesState 驱动模型/工具循环。

graph.py 负责节点、路由和编译；loop.py 只驱动流，messages.py 处理消息；
model.py 装配模型，model_invocation.py 执行模型；tools 管读取与查询，executor.py 管工具并行执行。
核心不保存任务、completion ID 或事件队列；gRPC 路由直接将类型化输出编码为 protobuf，并负责编号与终态。
"""
