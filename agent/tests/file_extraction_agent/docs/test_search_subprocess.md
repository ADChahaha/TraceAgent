# test_search_subprocess.py

验证 `search_embedding` 的子进程路径：取消 kill、失败映射与真实 worker 端到端。

## 实现链路

```text
_search_embedding(state, query, top_k)
  -> asyncio.to_thread(load_index) 读取并缓存索引
  -> _build_worker_request：query/top_k/model_id/dimension/chunks/vectors_b64
  -> state.embedding.search_slot() 串行启动子进程
  -> _run_worker：create_subprocess_exec -> stdin 请求 -> stdout 响应
       finally 中 kill 子进程（取消、超时、失败都不留残留）
```

## 测试函数

- `test_search_cancellation_kills_worker`：慢 worker 启动后记录自身 pid；任务取消后断言进程已被 kill。
- `test_search_worker_failure_returns_error`：worker 以非 0 退出且无 stdout 时返回 `ok: false`，错误信息包含 stderr。
- `test_search_with_real_worker_returns_results`：本地模型缓存存在时跑真实 worker，返回 2 条结果；缺模型时跳过。
