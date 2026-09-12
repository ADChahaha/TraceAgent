# 文档问答 Agent

本包接收已准备的资源定位数组与完整历史消息，执行一轮模型/工具循环。`document_resources` 负责 HTML 转文件与文档 embedding 发布到 storage 服务；本包在 prepare 子进程中通过 storage 服务拉取 `documents.zip` 并校验索引，之后每次工具调用都把这份 workspace payload 交给新的工具子进程，父进程不执行资源读取。

```text
completion_id + resource_refs + messages + 模型/运行配置
  → 路由层 prepare_workspace 子进程：拉取归档 + 校验索引 → workspace payload
  → 路由装配问答模型并直接消费 stream_completion
  → build_tools(payload) 绑定四个工具；每次调用经 run_operation 启动工具子进程
  → build_qa_graph 绑定 RunOptions；图内 MessagesState 仅保存消息
  → 模型返回 AIMessage；有工具调用则并行执行并返回完整 ToolMessage 批次
  → completion_runtime 包装无 completion ID 的事件，按消费顺序加 seq 并输出事件字典，由 gRPC 接口编码
  → 完成、失败或取消后关闭本轮生成器，保留文档资源
```

## 文件与职责

- `completion_runtime.py`：stream_completion 异步生成器、事件包装、连续编号和内层流关闭。
- `core/loop.py`：校验输入、绑定子进程工具与消息，委托 graph 执行，转发输出并关闭内层流。
- `core/messages.py`：提示词、历史消息转换、响应校验与终止信号解析。
- `core/model_invocation.py`：模型调用、重试、退避和流式消息聚合。
- `core/executor.py`：并行执行工具、处理超时并封装结果。
- `core/graph.py`：绑定模型与工具执行器，构建并执行仅含消息的图，负责节点路由、取消边界、更新转换及图流关闭。
- `core/tools/workspace.py`：资源定位解析、拉取 `documents.zip`、序列化/还原 workspace payload。
- `core/tools/worker_client.py`：父进程侧子进程客户端，组装请求、等待响应并在 finally kill。
- `core/tools/embedding.py`：清单与索引读取校验、payload 序列化，以及检索工具工厂。
- `core/tools/worker.py`：统一工具子进程入口，按 operation 分发 prepare / ls / grep / read / search_embedding。
- `core/tools/ov_embedder.py`：纯 OpenVINO 查询编码器（tokenizer + IR + mean pooling + L2）。

工具只浏览 `documents/` key 前缀，内部 manifest/index 不暴露为文档。`grep` 用纯 Python 匹配候选；模型应 read 后为具体事实添加句尾数字引用。

## 调用入口

```python
import asyncio
from contextlib import aclosing

from service.file_extraction_agent.core.tools.worker_client import prepare_workspace
from service.file_extraction_agent.completion_runtime import stream_completion
from service.file_extraction_agent.core.model import build_qa_model
from service.file_extraction_agent.schemas import DocumentQaMessage, ResourceRef


async def main():
    # 替换成 PrepareResources 返回的实际定位，并预先配置问答模型。
    workspace = await prepare_workspace([
        ResourceRef(type="documents", location="s3://res_example/documents"),
        ResourceRef(type="index", location="s3://res_example/index"),
    ])
    stream = stream_completion(
        qa_model=build_qa_model(None),
        workspace=workspace,
        messages=[DocumentQaMessage(role="user", content="付款期限是多少？")],
    )
    async with aclosing(stream) as events:
        async for frame in events:
            print(frame)


if __name__ == "__main__":
    asyncio.run(main())
```

从 agent 目录、已激活的 agent-gate 环境运行此脚本。prepare_workspace 的预检在子进程执行；
stream_completion 返回异步生成器，aclosing 确保提前退出也关闭内层流。
模型配置和服务启动见 [服务 README](../../README.md)。

gRPC 入口是 ChatCompletion。无效资源在首事件前返回 INVALID_ARGUMENT；执行失败输出 completion.failed。取消原 call 时由 grpc.aio 取消 handler，沿 await 传播并清理模型、工具子任务和子进程，不输出取消终态。没有活动 ID 注册表，也没有单独取消接口。

详见 [设计](docs/DESIGN.md)、[循环](docs/agent_loop.md)、[工具](docs/tools.md) 和 [API](../../docs/API.md)。
