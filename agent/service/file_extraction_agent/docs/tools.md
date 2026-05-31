## fuzzy_search(未实现)
模糊搜索，输入关键词，返回符合条件的文件列表。

## ls文件
列出文件的section，返回section列表。
```python
def ls(path_id: str = "") -> dict[str, Any]:
```

## read
读取模型想要read的paragraph、table和list等内容。
```python
def read(locator: str) -> dict[str, Any]:
```

## inspect
inspect句子，作为输出引用，返回句子内容和标识符。
```python
def inspect(locator: str) -> dict[str, Any]:
```

## grep
文件内搜索(精细匹配)，输入关键词，返回符合条件的句子列表。
```python
def grep(query: str, scope: str = "", kind: str = "", max_results: int = 20) -> dict[str, Any]:
```