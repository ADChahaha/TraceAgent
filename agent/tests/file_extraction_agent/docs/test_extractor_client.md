# `test_extractor_client.py`

## 基本实现思路

`service.file_extraction_agent.extractor_client` 负责把“连接哪个 OpenAI 兼容服务”和“按什么结构化输出协议调用模型”拆开管理。连接信息优先来自显式参数，缺省时读取环境变量；如果环境里没有 `MODEL`，就使用代码内默认模型。结构化输出策略由调用方显式传入 `build_extractor_client(...)`，然后再统一构造一个可直接 `invoke(...)` 的抽取客户端。

这层可以按下面的 pipeline 理解：

```text
调用方进入 build_extractor_client(base_url, api_key, model, structured_output_strategy=...)
  -> 先显式指定 json_schema / tool_call / auto
  -> 优先使用显式传入的 base_url / api_key / model
  -> 缺省时读取 BASE_URL / OPENAI_API_KEY / MODEL
  -> 如果 MODEL 仍缺失，就使用 DEFAULT_MODEL
  -> extractor_client 检查连接参数是否齐全
  -> 用显式连接参数和代码内默认参数创建 ChatOpenAI(base_url=..., api_key=..., model=..., temperature=0)
  -> 先按显式参数选择 json_schema 或 tool_call
  -> 如果 structured_output_strategy=auto 且 json_schema 不支持，就回退到 tool_call
  -> 如果 json_schema runnable 已开始 invoke 后失败，直接返回结构化调用失败，不再重试 tool_call
  -> 返回能直接 invoke 的结构化 agent
  -> 如果结构化 runnable 调用失败，不再解析裸 JSON 文本或裸 tool call 参数
```

## 测什么

- 缺少连接参数且环境变量也没有时会明确报错
- 显式参数缺省时会从环境变量读取连接配置
- 环境变量没有 `MODEL` 时会使用默认模型
- `json_schema` 策略会按严格 schema 方式构造 runnable
- `tool_call` 策略会映射到 LangChain 的 `function_calling`
- `auto` 策略会在 `json_schema` 不支持时回退到 `tool_call`
- `auto` 策略不会把 json_schema 调用阶段的超时、鉴权、服务端错误或输出校验失败当成协议不支持并重试
- 结构化调用失败后不会再调用裸 `model.invoke(...)` 解析 JSON 文本
- 结构化调用失败后不会再解析裸 tool call arguments
- 非法策略参数会被拒绝

## 每个函数在干什么

`test_build_extractor_client_from_env_requires_all_runtime_variables`

- 清空 `BASE_URL`、`OPENAI_API_KEY`、`MODEL`。
- 故意不传 `base_url`、`api_key`、`model`。
- 确认构造函数会拒绝继续执行，并把缺失连接参数名写进异常消息。

`test_build_extractor_client_uses_environment_when_arguments_are_omitted`

- 设置 `BASE_URL`、`OPENAI_API_KEY`、`MODEL` 环境变量。
- 不显式传连接参数，调用 `build_extractor_client(...)`。
- 确认底层 `ChatOpenAI` 使用环境变量中的连接信息。

`test_build_extractor_client_defaults_model_when_env_model_is_omitted`

- 设置 `BASE_URL` 和 `OPENAI_API_KEY`，清空 `MODEL`。
- 不显式传 `model`，调用 `build_extractor_client(...)`。
- 确认底层 `ChatOpenAI` 使用代码内默认模型。

`test_build_extractor_client_from_env_uses_json_schema_strategy_argument`

- 用假的 `ChatOpenAI` 替身拦住真实网络调用。
- 确认连接参数和模型名都来自显式参数，默认请求参数来自代码，结构化策略也来自显式参数，而且最终返回对象可直接 `invoke(...)`。

`test_build_extractor_client_from_env_uses_tool_call_strategy_argument`

- 确认内部会把显式传入的 `tool_call` 映射成 LangChain 需要的 `function_calling`。

`test_build_extractor_client_from_env_falls_back_to_tool_call_when_json_schema_is_unsupported`

- 让假的 `ChatOpenAI` 在 `json_schema` 时抛错。
- 确认 client 会继续尝试 `tool_call`，而不是直接失败。

`test_auto_strategy_does_not_retry_tool_call_after_json_schema_invoke_failure`

- 让假的 `json_schema` structured runnable 在 `invoke(...)` 阶段抛出超时类错误。
- 确认 client 不会继续调用 `function_calling`，避免一次业务调用被换协议重复执行。

`test_invoke_rejects_raw_json_content_when_structured_invoke_fails`

- 让假的结构化 runnable 在调用时抛错。
- 即使底层裸模型能返回 JSON 文本，也确认 client 直接返回结构化调用失败。

`test_invoke_rejects_raw_tool_call_arguments_when_structured_invoke_fails`

- 让假的结构化 runnable 在调用时抛错。
- 即使底层裸模型能返回 tool call arguments，也确认 client 不解析这类非结构化回退结果。

`test_build_extractor_client_from_env_rejects_unknown_structured_output_strategy_argument`

- 传入一个非法策略名。
- 确认构造阶段就会把这类坏参数拦住。

## 怎么跑

```bash
conda activate agent-gate
cd agent
python -m pytest tests/file_extraction_agent/test_extractor_client.py -q
```
