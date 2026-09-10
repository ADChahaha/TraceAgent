# test_ov_embedder.py

验证纯 OpenVINO 查询编码器：tokenizer + IR → mean pooling → L2 归一化，且不需要 torch。

## 实现链路

```text
OpenVinoQueryEmbedder(model_id)
  -> 本地缓存优先解析模型目录（缺失才联网）
  -> tokenizers.Tokenizer.from_file(tokenizer.json)，设置截断/补齐
  -> ov.Core().compile_model(openvino/openvino_model.xml, CPU)
encode(texts)
  -> encode_batch 得到 input_ids / attention_mask
  -> IR 输出 last_hidden_state -> 按 mask 做 mean pooling -> 每行 L2 归一化
```

## 测试函数

- `test_encode_shape_and_unit_norm`：编码结果形状 `(n, 384)`、dtype 为 float32、每行单位长度。
- `test_encode_matches_sentence_transformers_reference_vectors`：与提交的参考向量（由 sentence-transformers 的 OpenVINO 后端一次性生成）余弦 > 0.999；本地模型 revision 与参考不一致时跳过。
- `test_ov_embedder_path_does_not_import_torch`：在子进程中运行编码，断言 `torch` / `sentence_transformers` 不在 `sys.modules`。

依赖 `openvino` 与本地模型缓存；缺失时相关测试跳过。
