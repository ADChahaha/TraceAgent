# 工具子进程、文档树引用与跨轮部署

返回 [文档问答执行设计](../DESIGN.md)。

## 工具模块与子进程分发

工具对模型暴露 async coroutine，executor 仅 `await tool.ainvoke`。每次工具调用都经 `worker_client.run_operation` 启动一次性子进程，将 `{operation, args, workspace}` 经 stdin 下发，父进程不执行对象读取或推理计算。

- 模块分工：`tools/ls.py`、`grep.py`、`read.py`、`embedding.py` 各自单文件；统一子进程入口为 `tools/worker.py`，父进程客户端为 `tools/worker_client.py`，纯 OpenVINO 查询编码器为 `tools/ov_embedder.py`，归档/payload 序列化在 `workspace.py`，异常归一化在 `base.py`。
- `run_tool` 只接收 execute 操作，普通异常转为 `ok:false`。工具工厂直接使用 LangChain `@tool` 返回 `BaseTool`，不保留缺依赖降级分支。

```text
prepare_workspace(resource_refs)
  -> 空数组直接抛 ValueError；否则启动 python -m ...tools.worker 执行 prepare
  -> load_workspace_payload 拉取归档、校验清单版本/模型/向量/引用
  -> 返回 {ok, workspace:{bucket, documents_archive_b64, index}}
  -> kind=invalid 映射 ValueError（INVALID_ARGUMENT）；其他失败映射 RuntimeError（INTERNAL）

ls / grep / read / search_embedding
  -> run_operation 下发 {operation, args, workspace} 到一次性 worker
  -> 只读工具经 document_tree_from_payload 重建文档树；search_embedding 解码索引并加载 OpenVINO 编码器
  -> stdout 返回工具 JSON；进程级失败转为 ok:false 与 errors
  -> 取消、超时或失败均在 finally kill 子进程
```

## OpenVINO 编码器与实测基准

- 查询模型不在父进程加载；prepare 子进程只加载并校验索引，检索子进程按需加载 OpenVINO 编码器。
- 查询编码只依赖 `openvino` + `tokenizers`，不导入 `torch`/`transformers`；文档索引构建仍在 document service 使用 `sentence-transformers`，问答不重建文档向量。
- 本机实测基准（OpenVINO CPU、默认模型）：检索子进程每次启动约 2.3s、峰值内存约 420MB、稳态编码约 3ms/条（对比 `sentence-transformers` 包装启动约 21s）。当前采用每次调用单进程换取可 kill 取消语义与实现简洁，不引入常驻 worker，也不限制并发。

## 四类工具与引用格式

- `ls(path="")`：逐层浏览归档 `documents/` 目录。
- `grep(query, scope="", max_results=20)`：纯 Python 遍历 `.md` 做忽略大小写的字面匹配。
- `read(path)`：读取真实 Markdown 文件，拒绝文档目录之外路径。
- `search_embedding(query, top_k=5)`：纯 OpenVINO 编码 query 召回文本与 `covered_files`，无 `scope` 参数。
- 完整输入输出与错误码示例见 [tools.md](../tools.md)。
- Markdown 文件树由资源模块创建：文档标题作顶层目录后缀，h1-h6 按层级建目录，paragraph/list/table 分别落文件并使用数字前缀排序，合并表格展开为 Markdown；内部 `index`/`manifest` 不对浏览工具暴露。
- 检索只提供候选，模型通过 `read` 核实正文后再引用。过程消息用可读标签链接，最终回答用句尾数字引用如 `[1](documents/0001-contract/0001-section/0001-block.md)`，直接复用工具返回的 key，不在末尾汇总 Sources 区；非文档问题可直接回答。
- 资源定位与工具路径分两层：RPC `resource_path` 保存 `s3://res_example/documents` 与 `index`；工具内使用相对 `documents/...` key，不传本机绝对路径或完整 S3 URL，展示端结合资源定位解析。

## 跨轮与部署边界

- 每轮历史完全来自调用方 append-only `messages`，保留 assistant `tool_calls` 与 tool 结果，不摘要或裁剪。
- 资源定位数组跨轮稳定，任务与定位关联由 backend 管理；agent 每个 RPC 直接持有执行流，不维护活动 completion 注册表，不接收任务 metadata。
