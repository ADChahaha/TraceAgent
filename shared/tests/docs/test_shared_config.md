# test_shared_config.md

对应测试文件：`tests/test_shared_config.py`

## 验证内容

验证 `traceagent_shared.config` 的 `config.toml` 加载、显式进程环境变量覆盖、目标地址推导、运行期环境注入与 shell 导出 CLI。

## 测试函数

- `test_load_config_reads_explicit_toml_and_env_overrides`：验证读取 `TRACEAGENT_CONFIG` 指定的 `config.toml`，推导 storage/agent/document 目标地址，以及同名环境变量覆盖文件值。
- `test_load_config_rejects_missing_explicit_path_and_invalid_types`：验证显式路径缺失抛 `FileNotFoundError`，TOML 语法错误与类型错误（如用布尔值代替整数/浮点数）显式抛 `ValueError`。
- `test_empty_env_disables_file_loading`：验证 `TRACEAGENT_CONFIG=""` 禁用配置文件加载。
- `test_apply_runtime_env_sets_hf_flag_without_overwriting_env`：验证 `[huggingface].disable_implicit_token` 注入 `HF_HUB_DISABLE_IMPLICIT_TOKEN=1` 且不覆盖已有进程环境变量。
- `test_cli_shell_exports_emits_escaped_values_and_hf_toggle`：验证 `collect_shell_exports`、`format_shell_exports` 与 `python -m traceagent_shared.config --shell-exports` 输出安全转义的导出语句。
