# test_search_subprocess.py

验证 `worker_client` 的子进程路径：取消/超时 kill、失败映射、prepare 错误映射与真实 worker 端到端。

## 实现链路

```text
run_operation(operation, args, workspace)
  -> asyncio.create_subprocess_exec(python -m ...tools.worker)
  -> stdin 写 JSON -> 等待 stdout 响应（120s 上限）
  -> 非 0 且无 stdout、非法 JSON、非对象 -> ok:false + errors
  -> finally kill 子进程（正常、超时、取消都不留残留）

prepare_workspace(resource_refs)
  -> 空数组直接 ValueError（不起进程）
  -> run_operation(operation="prepare", args={resource_path})
  -> kind=invalid 映射 ValueError；其他失败映射 RuntimeError
```

## 测试函数

- `test_run_operation_cancellation_kills_worker`：慢 worker 记录自身 pid；任务取消后断言进程已被 kill。
- `test_prepare_workspace_cancellation_kills_worker`：prepare 途中取消同样 kill 子进程，不等待其自然结束。
- `test_run_operation_failure_returns_error`：worker 非 0 退出且无 stdout 时返回 `ok:false`，错误含 stderr。
- `test_prepare_workspace_maps_invalid_resource_to_value_error`：worker 返回 `kind=invalid` 时父进程抛 ValueError。
- `test_prepare_workspace_empty_refs_rejects_without_worker`：空资源数组在父进程直接拒绝，不启动子进程。
- `test_real_worker_search_returns_results`：本地模型缓存存在时跑真实检索子进程，返回 2 条结果；缺模型时跳过。
