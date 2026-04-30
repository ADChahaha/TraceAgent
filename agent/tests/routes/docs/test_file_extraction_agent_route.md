# test_file_extraction_agent_route.py

这份测试文档对应 `tests/routes/test_file_extraction_agent_route.py`，覆盖 `service.file_extraction_agent` 的 HTTP 最终出口。

## 实现链路

```text
HTTP JSON 请求传入 blocks、markdown、显式 task_spec、run_options、metadata 和可选模型配置
  -> FastAPI app 挂载 file extraction router
  -> route 层用 service.file_extraction_agent.schemas 解析稳定输入对象
  -> structured_output_strategy 未显式传入时固定为 tool_call，json_schema / auto 会在请求解析阶段拒绝
  -> 调用 service.file_extraction_agent.processor.extract(...)
  -> 把 ExtractionResult 原样作为 JSON 响应返回
```

## 测试函数

- `test_file_extraction_agent_route_calls_business_extractor`
  - 验证 `/v1/file-extraction-agent/extract` 会把标准化 blocks、markdown、task_spec 和 metadata 转交给业务抽取入口。
  - 验证 HTTP 入口默认把 `structured_output_strategy` 固定传成 `tool_call`。
  - 验证 route 层返回业务入口产出的 `ExtractionResult`，不在 HTTP 层重做字段填充。

- `test_file_extraction_agent_route_passes_run_options_to_business_extractor`
  - 验证 HTTP payload 中的 `run_options` 会解析成公开契约 `RunOptions` 并传给业务抽取入口。
  - 覆盖 prompt budget 和 resolution 候选预算在 HTTP 路径上的配置入口。
  - 验证 route 层使用 `schemas.py` 中的全局运行选项契约。

- `test_file_extraction_agent_route_passes_stage_model_overrides`
  - 验证 HTTP payload 中的 `model`、`broad_model` 和 `resolution_model` 会一起传给业务抽取入口。
  - 覆盖 broad / resolution 可以使用不同模型的 HTTP 配置入口。

- `test_file_extraction_agent_route_rejects_json_schema_and_auto_strategies`
  - 验证 HTTP payload 显式传入 `json_schema` 或 `auto` 时会得到 HTTP 422。
  - 确认这些旧策略不会继续进入业务抽取入口。

- `test_file_extraction_agent_route_returns_422_for_missing_task_spec`
  - 验证业务入口发现缺少显式 `task_spec` 时，route 层会把该输入错误转换成 HTTP 422。

- `test_file_extraction_agent_route_rejects_task_spec_name_payload`
  - 验证 HTTP 层不再接受 `task_spec_name` 这类本地目录加载入口。
