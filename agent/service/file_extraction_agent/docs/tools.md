# 问答工具

四个工具都不在父进程读资源：workspace payload（归档 bytes + 已解析索引）由 prepare 子进程生成，
每次调用经 worker_client.run_operation 下发给一次性工具子进程执行。

```text
模型 tool_calls
  → executor 并发 await tool.ainvoke
  → 工具把 operation、参数和全量 workspace 下发给工具子进程
  → 子进程读取归档内对象、执行字面搜索或 query embedding
  → 返回 JSON 对象，由 executor 封装为 ToolMessage
  → 模型 read 核实候选内容后，使用返回的 key 引用
```

普通异常由 run_tool 转为 `{"ok":false,"errors":[{"message":"异常说明"}]}`；
工具共享超时由 executor 处理。取消、超时或结束都会 kill 工具子进程，不等待其自然结束。

## 路径如何传递

PrepareResources 返回 `s3://res_example/documents` 与 `s3://res_example/index`。
工作区据此固定 bucket；工具传入的路径是桶内 `documents/...` key。

```text
ls("") → entries[].path = documents/0001-contract
  → ls("documents/0001-contract") → 继续逐层浏览
  → read("documents/0001-contract/0001-section/0001-block.md")
  → 返回 path + text
  → 回答引用 [1](documents/0001-contract/0001-section/0001-block.md)
```

以下 key 和文本仅为示例，实际调用需原样复制工具输出。不要传本机绝对路径或
s3:// URL；引用 key 也不是 HTTP 下载地址，展示端需结合资源定位解析。

## ls(path="")

空路径使用 documents 根；非空路径作为目录 key 校验后列出直接子目录和 .md 文件。
不递归展开，也不返回正文。

调用 `ls("documents/0001-contract/0001-section")` 的成功结果示例：

```json
{"ok":true,"path":"documents/0001-contract/0001-section","entries":[{"name":"0001-block.md","path":"documents/0001-contract/0001-section/0001-block.md","kind":"md","order":1}],"text":"0001-block.md"}
```

调用 `ls("index")` 返回 `ok:false`，errors 中说明路径越界；无可列出对象时 entries 为空。

## grep(query, scope="", max_results=20)

校验非空 query → 确定 scope key 前缀 → 遍历 .md 对象 → 忽略大小写地匹配字面文本
→ 返回 `key:行号:正文` 字符串。query 经 re.escape，不支持用户正则表达式。
max_results 默认 20，范围限制为 1–50；传 0 使用默认值。

调用 `grep("付款", scope="documents/0001-contract")` 的成功结果示例：

```json
{"ok":true,"query":"付款","scope":"documents/0001-contract","output":"documents/0001-contract/0001-section/0001-block.md:1:付款期限为30天。"}
```

空 query 返回 `{"ok":false,"errors":[{"code":"BAD_QUERY","message":"query is required"}]}`。
没有匹配时 output 为空字符串。当前 scope 越界会把错误文字放进 output，外层仍为
`ok:true`；调用方不能仅凭 ok 判断是否获得候选。候选必须通过 read 核实后再引用。

## read(path)

校验非空路径 → 检查 key 属于文档前缀 → 读取对象并按 UTF-8 解码 → 返回 Markdown。
段落为正文，列表为 Markdown 列表，表格为 Markdown 表格。

调用 `read("documents/0001-contract/0001-section/0001-block.md")` 的成功结果示例：

```json
{"ok":true,"path":"documents/0001-contract/0001-section/0001-block.md","text":"付款期限为30天。"}
```

调用 `read("index/index.json")` 返回：

```json
{"ok":false,"errors":[{"code":"BAD_PATH","message":"path escapes the document workspace: index/index.json"}]}
```

空路径、越界或对象缺失使用 BAD_PATH；其他普通异常使用通用 errors 结果。

## search_embedding(query, top_k=5)

校验 query → 在一次性工具子进程里从 `workspace.index` 解码 chunks/vectors
→ 加载清单指定的 OpenVINO 查询模型 → encode([query])
→ 归一化查询向量，按相似度排序 → 返回候选及 covered_files。
不重建文档向量，不支持 scope。top_k 默认 5，范围限制为 1–20；传 0 使用默认值。

调用 `search_embedding("付款期限", top_k=1)` 的结果结构示例（分数及 token 范围为示意值）：

```json
{"ok":true,"query":"付款期限","results":[{"score":0.9,"document":"0001-contract","chunk_id":"0001-contract#c1","text":"付款期限为30天。","token_range":[0,8],"covered_files":["documents/0001-contract/0001-section/0001-block.md"]}]}
```

空 query 返回与 grep 相同的 BAD_QUERY。索引损坏、模型加载失败或向量维度不符，
返回 `ok:false` 与 errors。一个 chunk 可能跨多个文件，应 read 对应 covered_files 后引用。
