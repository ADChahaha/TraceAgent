# file_extraction_agent 流程图

## chat completions

```mermaid
flowchart TD
    A[HTTP POST /v1/document-qa/chat/completions]
    A --> B["route 解析 ChatCompletionRequest<br/>Pydantic 强类型"]
    B --> C["completion_manager.create<br/>prepare_completion_state 校验 + materialize_tree 落盘 -> GraphState"]
    C --> D["build_resolution_model(model_config)<br/>-> ChatModelFallbackChain"]
    D --> E["构造 ActiveCompletion(completion_id, state, model)<br/>并注册进注册表"]
    E --> F["ActiveCompletion.stream()<br/>返回 SSE 生成器（首次 next 才启动 producer 线程）"]
    F --> G["producer 线程: _produce()<br/>manager.run_completion_graph_stream(state, model, should_stop)"]
    G --> H["manager: completion.created -> source_indexed -> loop.run_resolution_stream"]
    H --> I["core/loop (LangGraph): agent ⇄ tools"]
    I --> J["_produce 用 commit_event / commit_terminal_event 投事件到 queue"]
    J --> K["consumer: queue.get() -> yield SSE（每次 next() 取一条事件）"]
```

## cancel

```mermaid
flowchart TD
    A[HTTP POST /v1/document-qa/chat/completions/{id}/cancel]
    A --> B["completion_manager.terminate(id)"]
    B --> C{"在注册表找到 runtime?"}
    C -- 否 --> D["返回 not_found"]
    C -- 是 --> E["ActiveCompletion.terminate()<br/>锁内置 cancel_requested=true"]
    E --> F{"当前有运行中工具批次?"}
    F -- 否 --> H["放 _QUEUE_CANCEL 哨兵<br/>consumer 被唤醒 -> close_once('cancelled') -> completion.cancelled"]
    F -- 是 --> I["标记 deferred cancel<br/>should_stop 在批次结束后触发 completion.cancelled"]
    H --> G["producer 后续 commit 全部被拒，停止"]
    I --> G
```

> 注：本图描述高层线程/队列关系，实现细节以 `docs/DESIGN.md` 为准；`agent_loop.md` 见协作式取消与 LangGraph 环。
