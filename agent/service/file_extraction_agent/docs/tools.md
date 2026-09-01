# 工具表面

QA completion 只暴露三个工具，全部在真实文件树上操作。没有 `path_id` /
`evidence://` / `inspect`；引用证据直接用真实 `.md` 文件路径。

## ls

列出当前目录层的一个层级。
```python
def ls(path: str = "") -> dict[str, Any]:
```

## grep

在 scope 目录（默认整个 workspace 根）跑 ripgrep，返回原样 stdout。
```python
def grep(query: str, scope: str = "", max_results: int = 20) -> dict[str, Any]:
```

## read

读取一个 `.md` block 文件的 markdown 内容。
```python
def read(path: str) -> dict[str, Any]:
```
