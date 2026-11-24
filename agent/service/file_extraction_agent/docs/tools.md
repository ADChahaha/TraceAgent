# 问答工具

四个工具都不在父进程读资源：workspace payload（归档 bytes + 已解析索引）由 prepare 子进程生成，每次调用经 `worker_client.run_operation` 下发给一次性工具子进程执行。

```text
模型 tool_calls
  -> executor 并发 await tool.ainvoke
  -> 工具把 operation、参数和全量 workspace 下发给工具子进程
  -> 子进程读取归档内对象、执行字面搜索或 query embedding
  -> 返回 JSON 对象，由 executor 封装为 ToolMessage
  -> 模型 read 核实候选内容后，使用返回的 key 引用
```

普通异常由 `run_tool` 转为 `{"ok":false,"errors":[{"message":"异常说明"}]}`；工具共享超时由 executor 处理。取消、超时或结束都会 kill 工具子进程，不等待其自然结束。

## 目录

| 主题 | 文档 | 内容 |
| --- | --- | --- |
| 路径与文件工具 | [tools/file-tools.md](tools/file-tools.md) | `documents/...` key 规则及 `ls` / `grep` / `read` 示例与错误码 |
| 语义检索 | [tools/embedding-search.md](tools/embedding-search.md) | `search_embedding` 流程、`top_k` 边界、结果结构与 `covered_files` 规则 |

相关：[DESIGN.md](DESIGN.md) / [子进程与基准](design/tools-and-deployment.md)
