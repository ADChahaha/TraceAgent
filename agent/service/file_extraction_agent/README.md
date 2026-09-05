# 文档问答 Agent

本包接收已准备的资源路径与完整历史消息，执行一轮模型/工具循环。`document_resources` 负责 HTML 转文件与文档 embedding 落盘；本包通过工具读取磁盘产物，不导入资源生成包。

```text
completion_id + resource_path + messages + 模型/运行配置
  → CompletionManager 委托工具层预检，装配问答模型并注册 ActiveCompletion
  → GraphState 保存 resource_path、messages、RunOptions
  → build_tools 创建 ToolWorkspace，绑定 ls / grep / read / search_embedding
  → 模型返回 AIMessage；有工具调用则并行执行并返回完整 ToolMessage 批次
  → manager 包装事件，ActiveCompletion 按 FIFO 加 seq 并编码 SSE
  → 完成、失败或取消后移除本轮运行时，保留文档资源
```

## 文件与职责

- `manager.py`：注册、取消、事件包装与 SSE，不读取文档或持有 embedding 状态。
- `core/graph.py`：执行输入；`core/loop.py`：模型与工具循环。
- `core/tools/workspace.py`：目录归属与路径校验、文件浏览与读取、资源树数据。
- `core/tools/embedding.py`：清单和索引读取、查询模型缓存、query 编码及相似度检索。

工具只浏览 `resource_path/documents/`，内部 manifest/index 不暴露为文档。`grep` 与语义检索返回候选；模型应 read 后为具体事实添加句尾数字引用。

## 调用入口

```python
from service.file_extraction_agent.manager import completion_manager
from service.file_extraction_agent.schemas import DocumentQaMessage

stream = completion_manager.create(
    completion_id="cmp_001",
    resource_path="/absolute/resources/res_example",
    messages=[DocumentQaMessage(role="user", content="付款期限是多少？")],
)
for frame in stream:
    print(frame)
```

HTTP 入口是 `POST /v1/document-qa/chat/completions`。无效资源在事件流开始前返回 422；运行失败由 completion.failed 收口。取消时已发布工具批次先返回完整结果，再结束本轮；底层同步线程不能强杀。注册表仅在进程内有效，按单 worker 部署。

详见 [设计](docs/DESIGN.md)、[循环](docs/agent_loop.md)、[工具](docs/tools.md) 和 [API](../../docs/API.md)。
