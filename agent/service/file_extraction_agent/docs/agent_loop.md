# 问答执行链

路由消费 stream_completion 异步生成器；函数直接推进模型/工具执行并输出编号事件，不创建独立运行时。

```text
路由收到资源定位、历史与配置
  → prepare_workspace 拉取并校验归档和索引
  → build_qa_model 装配模型
  → stream_completion 输出 completion.created
  → stream_completion_events 输出 source_indexed，消费 run_qa_stream
  → build_tools 绑定 workspace，build_qa_messages 转换完整历史
  → graph 执行模型 / retry_wait / 并行工具节点
  → loop 将 messages、updates、custom 转为模型增量、完整消息和工具结果
  → stream_completion_events 转为业务字典，stream_completion 追加 seq
  → 正常完成输出 completion.completed；普通异常输出 completion.failed
```

RPC 取消沿 await 传播，CancelledError 不转换成失败；handler 使用 aclosing 逐层关闭流，executor 清理工具 Task，worker_client kill 子进程。没有按 ID 注册或查找执行的机制。资源和完整会话历史的持久化生命周期由调用方管理。
