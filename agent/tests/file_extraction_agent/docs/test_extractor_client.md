# `test_extractor_client.py`

## 基本实现思路

`file_extraction_agent.extractor_client` 负责把“连接哪个 OpenAI 兼容服务”和“用哪种结构化输出策略”拆开管理。连接信息继续来自环境变量，结构化输出策略和 fallback 顺序来自 `model_client_config.json`，然后再统一构造一个可直接 `invoke(...)` 的抽取客户端。

这层可以按下面的 pipeline 理解：

```text
进程环境里的 BASE_URL / OPENAI_API_KEY / MODEL
  -> extractor_client 检查连接信息是否齐全
  -> 读取 model_client_config.json 里的 structured_output.strategy 和 fallback_order
  -> 用 env 配置创建 ChatOpenAI(base_url=..., api_key=..., model=...)
  -> 先按 strategy 选择 json_schema 或 tool_call
  -> 如果 strategy=auto 且 json_schema 不支持，就回退到 tool_call
  -> 返回能直接 invoke 的结构化 agent
```

## 测什么

- 缺少环境变量时会明确报错
- `json_schema` 策略会按严格 schema 方式构造 runnable
- `tool_call` 策略会映射到 LangChain 的 `function_calling`
- `auto` 策略会在 `json_schema` 不支持时回退到 `tool_call`
- 非法策略配置会被拒绝
- 兼容旧入口 `build_model_client_from_env`

## 每个函数在干什么

`test_build_extractor_client_from_env_requires_all_runtime_variables`

- 清空 `BASE_URL`、`OPENAI_API_KEY`、`MODEL`。
- 确认构造函数会拒绝继续执行，并把缺失变量名写进异常消息。

`test_build_extractor_client_from_env_uses_json_schema_strategy_from_config`

- 写一份显式要求 `json_schema` 的临时配置文件。
- 用假的 `ChatOpenAI` 替身拦住真实网络调用。
- 确认连接参数来自环境变量，结构化策略来自配置文件，而且最终返回对象可直接 `invoke(...)`。

`test_build_extractor_client_from_env_uses_tool_call_strategy_from_config`

- 写一份 `tool_call` 配置。
- 确认内部会把仓库配置里的 `tool_call` 映射成 LangChain 需要的 `function_calling`。

`test_build_extractor_client_from_env_falls_back_to_tool_call_when_json_schema_is_unsupported`

- 写一份 `auto + [json_schema, tool_call]` 配置。
- 让假的 `ChatOpenAI` 在 `json_schema` 时抛错。
- 确认 client 会继续尝试 `tool_call`，而不是直接失败。

`test_build_extractor_client_from_env_rejects_unknown_structured_output_strategy`

- 写入一个非法策略名。
- 确认构造阶段就会把这类坏配置拦住。

`test_build_model_client_from_env_aliases_extractor_builder`

- 把旧入口替换成一个哨兵返回值。
- 确认兼容别名仍会转发到新的 extractor builder，避免上层调用点立刻失效。

## 怎么跑

```bash
source <conda-env>/etc/profile.d/conda.sh
conda activate agent-gate
cd ./agent
python -m pytest tests/file_extraction_agent/test_extractor_client.py -q
```
