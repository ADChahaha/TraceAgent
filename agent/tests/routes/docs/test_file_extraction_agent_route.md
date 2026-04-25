# test_file_extraction_agent_route.py

这份测试文档对应 `tests/routes/test_file_extraction_agent_route.py`，覆盖 `file_extraction_agent` 的 HTTP 最终出口。

## 实现链路

```text
HTTP JSON 请求传入 blocks、markdown、task_spec/task_spec_name 和 metadata
  -> FastAPI app 挂载 file extraction router
  -> route 层用 file_extraction_agent.schemas 解析稳定输入对象
  -> 调用 file_extraction_agent.processor.extract(...)
  -> 把 ExtractionResult 原样作为 JSON 响应返回
```

## 测试函数

- `test_file_extraction_agent_route_calls_business_extractor`
  - 验证 `/v1/file-extraction-agent/extract` 会把标准化 blocks、markdown、task_spec 和 metadata 转交给业务抽取入口。
  - 验证 route 层返回业务入口产出的 `ExtractionResult`，不在 HTTP 层重做字段填充。

- `test_file_extraction_agent_route_returns_422_for_missing_task_spec`
  - 验证业务入口发现缺少 `task_spec` / `task_spec_name` 时，route 层会把该输入错误转换成 HTTP 422。
