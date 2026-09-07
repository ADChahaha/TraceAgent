# 工具表面

QA completion 暴露四个异步工具，读取真实文件树和已有 embedding 索引。没有 `path_id` /
`evidence://` / `inspect`；引用证据直接用真实 `.md` 文件路径。

模型 tool_calls → executor 并发 await tool.ainvoke → 工具协程用 asyncio.to_thread 执行同步文件操作、ripgrep 或本地 embedding → 返回结果并封装 ToolMessage。普通异常与共享超时返回失败结果；取消协程不强杀已经运行的同步线程。

返回类型 JsonObject 是 dict[str, JsonValue]，只包含可序列化的 JSON 值。run_tool(execute) 负责异常归一化，不再接收未使用的状态、工具名或参数。

## ls

列出当前目录层的一个层级。
```python
async def ls(path: str = "") -> JsonObject:
```

## grep

在 scope 目录（默认整个 workspace 根）跑 ripgrep，返回原样 stdout。
```python
async def grep(query: str, scope: str = "", max_results: int = 20) -> JsonObject:
```

## read

读取一个 `.md` block 文件的 markdown 内容。
```python
async def read(path: str) -> JsonObject:
```

## search_embedding

使用资源清单指定的模型编码 query，从已有索引返回 top-k 候选及真实文件引用；不重建文档向量。

```python
async def search_embedding(query: str, top_k: int = 5) -> JsonObject:
```

已删除未参与过滤的 scope 参数。检索结果应通过 read 核实后引用。
