# test_file_extraction_agent_route.py

这份测试文档对应 `tests/routes/test_file_extraction_agent_route.py`，覆盖 `service.file_extraction_agent` 的 HTTP 最终出口。

## 实现链路

```text
HTTP JSON 请求传入 html、task_spec、run_options 和可选模型配置
  -> FastAPI app 挂载 file extraction router
  -> route 层用 service.file_extraction_agent.schemas 解析稳定输入对象
  -> 调用 service.file_extraction_agent.processor.extract(...)
  -> 把 ExtractionResult 原样作为 JSON 响应返回
```

## 测试函数

- `test_file_extraction_agent_route_calls_html_extractor`
  - 验证 `/v1/file-extraction-agent/extract` 会把 HTML 和 task_spec 转交给业务抽取入口。
  - 验证 route 层返回业务入口产出的 `ExtractionResult`，不在 HTTP 层重做字段填充。

- `test_file_extraction_agent_route_passes_run_options`
  - 验证 HTTP payload 中的 `run_options` 会解析成公开契约 `RunOptions` 并传给业务抽取入口。
  - 覆盖 resolution tool budget 在 HTTP 路径上的配置入口。
  - 验证 route 层使用 `schemas.py` 中的全局运行选项契约。

- `test_file_extraction_agent_route_passes_resolution_model_overrides`
  - 验证 HTTP payload 中的 `base_url`、`openai_api_key`、`resolution_model_name` 和采样参数会传给业务抽取入口。
  - 覆盖单 resolution model 的 HTTP 配置入口。

- `test_file_extraction_agent_route_accepts_model_config_object`
  - 验证 `model_config` 对象会按 `ModelConfig` 解析并传给业务抽取入口。

- `test_file_extraction_agent_route_rejects_broad_model_override`
  - 验证 HTTP 层不再接受旧的 `broad_model_name` 覆盖字段。

- `test_file_extraction_agent_route_rejects_nested_broad_model_override`
  - 验证嵌套 `model_config` 中的旧 `broad_model_name` 也会被拒绝，而不是进入业务层形成运行时错误。

- `test_file_extraction_agent_route_returns_422_for_business_validation`
  - 验证业务入口抛出的输入错误会被 route 层转换成 HTTP 422。

- `test_file_extraction_agent_route_rejects_unknown_payload_fields`
  - 验证 HTTP 层不接受未声明字段。
