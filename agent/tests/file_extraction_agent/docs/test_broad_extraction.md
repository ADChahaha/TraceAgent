# `test_broad_extraction.py`

## 基本实现思路

这个测试文件约束 `file_extraction_agent.impl.broad_extraction` 的第一阶段节点行为。

```text
GraphState(extraction_input=..., evidence_collection=None)
  -> run_broad_extraction(...) 读取 state.extraction_input
  -> build_broad_extraction_messages(extraction_input)
  -> extractor_client.invoke(output_schema=EvidenceCollection, messages=...)
  -> 将返回的 EvidenceCollection 写入 state.evidence_collection
```

## 覆盖点

- 节点会请求 `EvidenceCollection`
- 节点会把输出写回 `state.evidence_collection`
- 返回值仍然是同一个 `GraphState`

## 每个函数在干什么

`test_run_broad_extraction_invokes_client_and_writes_output_to_state`

- 构造一份最小 `ExtractionInput` 和空状态。
- 用假的 extractor client 返回固定 `EvidenceCollection`。
- 确认 broad 节点会按新内部契约写回状态。

## 运行方式

```bash
source <conda-env>/etc/profile.d/conda.sh
conda activate agent-gate
cd ./agent
python -m pytest tests/file_extraction_agent/test_broad_extraction.py -q
```
