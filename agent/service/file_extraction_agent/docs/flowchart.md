# 文档准备与问答流程图

上传入口先准备持久资源；问答入口只传路径，graph 内部初始化执行状态。

```mermaid
flowchart TD
    A["PrepareResources: filename + bytes"] --> B["document_processor: PDF / DOCX → HTML"]
    B --> C["document_resources: 文件树 + embedding 索引 + manifest"]
    C --> D["返回 resource_path + documents"]
    D --> E["调用方保存路径与 HTML"]
    E --> F["ChatCompletion: resource_path + messages"]
    F --> G["manager 委托工具预检、创建问答模型、注册 CompletionRuntime"]
    G --> H["loop 初始化工具与消息；graph 绑定执行函数并运行节点/路由；图内完整 messages 与重试状态"]
    H --> I["loop 消费 LangGraph: messages 增量 / updates 模型结果 / custom 单个工具结果"]
    I --> J["completion_runtime 包装事件字典"]
    J --> K["CompletionRuntime: queue → 唤醒异步消费者 → seq → 事件字典 → protobuf 流"]
    K --> L["移除本轮运行时，保留资源"]
```

## 取消

```mermaid
flowchart TD
    A["CancelCompletion(id)"] --> B["manager 查 active runtime"]
    B --> C{"找到？"}
    C -- 否 --> D["not_found"]
    C -- 是 --> E["锁内设置 cancel_requested"]
    E --> F["取消 producer；Task 完成回调唤醒 consumer"]
    E --> R["取消 RPC 立即返回 cancelling；注册项移除后返回 not_found"]
    F --> G["executor 取消未完成工具 Task，等待 finally 清理"]
    G --> I["取消后停止输出队列内容，清理后直接关闭，不发取消终态"]
```

具体契约以 [DESIGN.md](DESIGN.md) 为准。

## 模型请求与重试

```mermaid
flowchart TD
    A[agent: 固定配置单次请求] --> B{结果}
    A -. messages 原生回调 .-> S[文本增量]
    B -->|成功有工具| T[tools]
    T --> A
    B -->|成功无工具| E[结束]
    B -->|失败且未达五次| R[updates 失败通知 → retry_wait 指数退避]
    R --> A
    B -->|第五次失败| F[completion.failed]
```
