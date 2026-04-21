# `test_broad_extraction.py`

这个测试文件约束 `file_extraction_agent.impl.broad_extraction` 的第一阶段节点行为。它不测试模型能力，也不做字段定案；它只确认 broad extraction 节点会从内部 `GraphState` 读取已经组装好的 `GraphInput`，调用抽取客户端拿到 `BroadExtractionOutput`，再把结果写回同一个状态对象。

实现链路：

```text
GraphState(graph_input=..., broad_output=None)
  -> run_broad_extraction(...) 读取 state.graph_input
  -> build_broad_extraction_messages(graph_input) 生成模型 messages
  -> extractor_client.invoke(output_schema=BroadExtractionOutput, messages=...)
  -> 将返回的 BroadExtractionOutput 写入 state.broad_output
  -> 返回原来的 GraphState，供后续 validation / resolution 节点继续接力
```

## 覆盖点

- `test_run_broad_extraction_invokes_client_and_writes_output_to_state`：构造一份带发票号字段的 `GraphInput` 和空 `GraphState`，用假的 extractor client 返回固定 `BroadExtractionOutput`；确认节点会请求 `BroadExtractionOutput` 结构、prompt 中包含 session 内容、输出被写回 `state.broad_output`，且返回的是同一个状态对象。

## 运行方式

```bash
conda run -n agent-gate python -m pytest tests/file_extraction_agent/test_broad_extraction.py -q
```
