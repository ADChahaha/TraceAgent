# 语义检索工具（`search_embedding`）

本页属 [问答工具](../tools.md)，说明 `search_embedding(query, top_k=5)` 的执行路径、参数边界、结果结构与异常处理。

## 执行流程与参数

```text
校验非空 query
  -> 一次性工具子进程从 workspace.index 解码 chunks 与 vectors
  -> 加载清单指定的 OpenVINO 查询模型 -> encode([query])
  -> 归一化查询向量，按相似度排序
  -> 返回候选片段与 covered_files
```

- 不重建文档向量，不支持 `scope` 参数。
- `top_k` 默认 5，范围限制为 1-20；传 0 使用默认值。

## 结果结构示例

调用 `search_embedding("付款期限", top_k=1)` 的返回结构（分数与 token 范围为示意值）：

```json
{
  "ok": true,
  "query": "付款期限",
  "results": [
    {
      "score": 0.9,
      "document": "0001-contract",
      "chunk_id": "0001-contract#c1",
      "text": "付款期限为30天。",
      "token_range": [0, 8],
      "covered_files": ["documents/0001-contract/0001-section/0001-block.md"]
    }
  ]
}
```

## 错误与引用约束

- 空 `query` 返回与 `grep` 相同的 `BAD_QUERY` 错误结构。
- 索引损坏、模型加载失败或向量维度不符时返回 `ok:false` 与 `errors`。
- 单个 chunk 可能跨越多个 Markdown 文件，模型必须通过 `read` 核实对应 `covered_files` 正文后再引用。
