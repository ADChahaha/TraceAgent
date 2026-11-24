# 取消、探活与错误码

返回 [Agent gRPC API](../API.md)。

## 取消与连接生命周期

客户端保存原 call，停止消费时在 `finally` 中取消，不再发单独的 `CancelCompletion` RPC：

```python
call = client.ChatCompletion(request, timeout=300)
try:
    for event in call:
        print(event)
        if event.type == "model_message.delta":
            break  # 示例：提前停止消费。
finally:
    call.cancel()
```

```text
原 call.cancel() / deadline / 已检测到的断连
  -> grpc.aio 取消对应 handler
  -> 取消沿 await 传播到模型/图执行
  -> aclosing 逐层关闭生成器
  -> executor 清理工具 Task，run_operation finally kill 子进程
```

- `application.stream_completion` 是异步生成器函数，预检后输出带 `seq` 的业务事件；无 manager、运行时对象、独立 producer 或内存事件队列。
- 正常完成/普通失败输出唯一终态，取消不生成终态。gRPC 负责传输流控，handler 退出时关闭当前生成器（含暂停在 `yield` 时）。
- `call.cancel()` 同步返回，只表示本地取消请求结果，不确认远端清理完成。backend 自行记录取消状态并拒绝迟到写入；RPC 意外断开不能视为成功完成。
- 同步阻塞工作不会被 asyncio 强制中断，取消不撤销已产生的副作用。资源保留供下一轮使用。

## 探活接口

- agent 不提供问答查询接口；本轮进展与终态通过 `ChatCompletion` 事件流返回，历史查询由 backend 管理。
- 标准 `grpc.health.v1.Health/Check`：agent 使用 `traceagent.v1.AgentService`，document service 使用 `traceagent.v1.DocumentResourceService`；服务名为空也返回 `SERVING`，仅用于进程探活，不检查模型可用性。

## 错误映射与调用注意

| 情况 | 响应 |
| --- | --- |
| 上传类型/参数、消息或资源校验失败 | `INVALID_ARGUMENT`，首事件前返回 |
| 文档解析、资源准备或问答初始化异常 | `INTERNAL` |
| 开始执行后的模型/工具循环异常 | 原流的 `completion.failed`；普通工具失败可继续执行 |
| 消息超过配置上限 | `RESOURCE_EXHAUSTED` |
| 客户端直接取消或 deadline 到期 | 客户端观察 `CANCELLED` / `DEADLINE_EXCEEDED` |

- 调用 RPC 时按 OCR、embedding 或问答实际耗时设置 deadline。
- 本版不提供持久幂等、事件重放或持久任务；若响应丢失，服务端可能已经执行，重试资源准备或问答创建前需留意重复执行。
