# Core 清理验证

单一模型或混合内容块输入 → 绑定工具/调用或提取文本 → 验证配置与可见结果，不请求外部模型。

- `test_single_model_binding_preserves_invoke_mode`：直接保存单个 provider，绑定工具后保留非流式调用方式。
- `test_deepseek_uses_standard_model_without_custom_thinking`：DeepSeek 名称使用普通模型类，不再注入专用 thinking 参数。
- `test_visible_text_ignores_non_text_and_invalid_blocks`：文本与 text 块统一提取，忽略推理和无效文本值。

模型类通过延迟加载工厂替换，不导入真实 SDK 或发起网络请求。
