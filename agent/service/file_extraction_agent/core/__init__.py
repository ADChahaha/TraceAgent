"""问答核心：资源路径初始化工具 → 运行配置绑定执行器 → MessagesState 驱动模型/工具循环。

graph.py 负责节点、路由和编译；loop.py 只驱动流，messages.py 处理消息；
model.py 装配模型，model_invocation.py 执行模型；tools 管读取与查询，executor.py 管工具并行执行。
核心不保存任务、completion ID 或事件队列；manager 负责注册表，completion_runtime 负责单轮运行时与 SSE。
"""
