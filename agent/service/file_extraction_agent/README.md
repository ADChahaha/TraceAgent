# 文档问答 Agent

本包接收已准备的资源定位数组与完整历史消息，执行一轮模型/工具循环。`document_resources` 负责 HTML 转文件与文档 embedding 发布到 storage 服务；本包通过 `S3ObjectStore`（boto3）从 storage 服务读取资源，不导入资源生成包。

```text
completion_id + resource_refs + messages + 模型/运行配置
  → CompletionManager 委托工具层预检，装配问答模型并注册 CompletionRuntime
  → open_workspace(resource_refs) 创建 ToolWorkspace，build_tools 绑定四个工具
  → build_qa_graph 绑定 RunOptions；图内 MessagesState 仅保存消息
  → 模型返回 AIMessage；有工具调用则并行执行并返回完整 ToolMessage 批次
  → completion_runtime 包装无 completion ID 的事件，按 FIFO 加 seq 并输出事件字典，由 gRPC 接口编码
  → 完成、失败或取消后移除本轮运行时，保留文档资源
```

## 文件与职责

- `manager.py`：创建、注册、查找运行时，转发取消/状态查询，注入运行时收尾时移除注册项的闭包。
- `completion_runtime.py`：单轮运行时、事件包装、生产协程、队列、异步事件等待与取消收尾。
- `core/loop.py`：校验输入、初始化工具与消息，委托 graph 执行，转发输出并关闭内层流。
- `core/messages.py`：提示词、历史消息转换、响应校验与终止信号解析。
- `core/model_invocation.py`：模型调用、重试、退避和流式消息聚合。
- `core/executor.py`：并行执行工具、处理超时并封装结果。
- `core/graph.py`：绑定模型与工具执行器，构建并执行仅含消息的图，负责节点路由、取消边界、更新转换及图流关闭。
- `core/tools/workspace.py`：资源定位解析、S3ObjectStore 读取、按 key 前缀浏览与读取。
- `core/tools/embedding.py`：清单和索引读取（经 storage 服务）、查询模型缓存、query 编码及相似度检索。

工具只浏览 `documents/` key 前缀，内部 manifest/index 不暴露为文档。`grep` 用纯 Python 匹配候选；模型应 read 后为具体事实添加句尾数字引用。

## 调用入口

```python
import asyncio
from contextlib import aclosing

from service.file_extraction_agent.manager import completion_manager
from service.file_extraction_agent.schemas import DocumentQaMessage, ResourceRef


async def main():
    # 替换成 PrepareResources 返回的实际定位，并预先配置问答模型。
    runtime = await asyncio.to_thread(
        completion_manager.create,
        completion_id="cmp_001",
        resource_path=[
            ResourceRef(type="documents", location="s3://res_example/documents"),
            ResourceRef(type="index", location="s3://res_example/index"),
        ],
        messages=[DocumentQaMessage(role="user", content="付款期限是多少？")],
    )
    async with aclosing(runtime.stream()) as events:
        async for frame in events:
            print(frame)


if __name__ == "__main__":
    asyncio.run(main())
```

从 agent 目录、已激活的 agent-gate 环境运行此脚本。create 的资源预检在线程执行；
stream 返回异步迭代器，aclosing 确保已开始消费的流在提前退出时也关闭并移除注册项。
模型配置和服务启动见 [服务 README](../../README.md)。

gRPC 入口是 `ChatCompletion`。无效资源在事件流开始前返回 INVALID_ARGUMENT；运行失败由 completion.failed 收口。取消时已发布工具批次先返回完整结果，再结束本轮；模型流和工具协程支持取消，工具内同步 I/O/计算线程不能强杀。注册表仅在进程内有效，使用单进程部署。

详见 [设计](docs/DESIGN.md)、[循环](docs/agent_loop.md)、[工具](docs/tools.md) 和 [API](../../docs/API.md)。
