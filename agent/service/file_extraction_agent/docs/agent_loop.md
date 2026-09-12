# 问答执行链

application.stream_completion 预检普通请求参数，stream_execution 消费 core 类型化输出并生成带编号的业务 CompletionEvent；路由编码函数编码 protobuf，不创建独立运行时或字典事件层。

```text
路由将资源定位、历史与配置适配为普通参数，传入 application.stream_completion
  → prepare_workspace 拉取并校验归档和索引
  → build_qa_model 装配模型
  → stream_execution 输出 completion.created
  → stream_execution 输出 source_indexed，直接消费 run_qa_stream
  → build_tools 绑定 workspace，build_qa_messages 转换完整历史
  → graph 执行模型 / retry_wait / 并行工具节点
  → loop 将 messages、updates、custom 转为模型增量、完整消息和工具结果
  → application 构造模型/工具/重试业务 CompletionEvent，追加 seq；路由编码函数编码 protobuf
  → 正常完成输出 completion.completed；普通异常输出 completion.failed
```

RPC 取消沿 await 传播，CancelledError 不转换成失败；handler 使用 aclosing 逐层关闭流，executor 清理工具 Task，worker_client kill 子进程。没有按 ID 注册或查找执行的机制。资源和完整会话历史的持久化生命周期由调用方管理。
