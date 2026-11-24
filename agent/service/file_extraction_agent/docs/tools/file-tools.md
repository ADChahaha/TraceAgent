# 路径传递与只读文件工具

本页属 [问答工具](../tools.md)，定义 `documents/...` key 传递规则以及 `ls`、`grep`、`read` 的契约与示例。

## 路径传递规则

`PrepareResources` 返回 `s3://res_example/documents` 与 `s3://res_example/index`。工作区据此固定 bucket，工具传入的路径是桶内 `documents/...` key：

```text
ls("") -> entries[].path = documents/0001-contract
  -> ls("documents/0001-contract") -> 继续逐层浏览
  -> read("documents/0001-contract/0001-section/0001-block.md")
  -> 返回 path + text
  -> 回答引用 [1](documents/0001-contract/0001-section/0001-block.md)
```

以下 key 和文本均为示例，实际调用须原样复制工具输出。禁止传入本机绝对路径或 `s3://` URL；引用 key 不是 HTTP 下载地址，展示端需结合资源定位解析。

## `ls(path="")`

空路径使用 `documents` 根；非空路径作为目录 key 校验后列出直接子目录和 `.md` 文件，不递归展开，也不返回正文。

调用 `ls("documents/0001-contract/0001-section")` 的成功结果示例：

```json
{"ok":true,"path":"documents/0001-contract/0001-section","entries":[{"name":"0001-block.md","path":"documents/0001-contract/0001-section/0001-block.md","kind":"md","order":1}],"text":"0001-block.md"}
```

调用 `ls("index")` 返回 `ok:false`，`errors` 中说明路径越界；无可列出对象时 `entries` 为空。

## `grep(query, scope="", max_results=20)`

校验非空 `query` -> 确定 `scope` key 前缀 -> 遍历 `.md` 对象 -> 忽略大小写匹配字面文本 -> 返回 `key:行号:正文` 字符串。`query` 经 `re.escape`，不支持用户正则表达式。`max_results` 默认 20，范围限制 1-50；传 0 使用默认值。

调用 `grep("付款", scope="documents/0001-contract")` 的成功结果示例：

```json
{"ok":true,"query":"付款","scope":"documents/0001-contract","output":"documents/0001-contract/0001-section/0001-block.md:1:付款期限为30天。"}
```

- 空 `query` 返回 `{"ok":false,"errors":[{"code":"BAD_QUERY","message":"query is required"}]}`。
- 无匹配时 `output` 为空字符串。
- 当前 `scope` 越界会把错误文字放进 `output`，外层仍为 `ok:true`；调用方不能仅凭 `ok` 判断是否获得候选，且候选必须经 `read` 核实后再引用。

## `read(path)`

校验非空路径 -> 检查 key 属于文档前缀 -> 读取对象并按 UTF-8 解码 -> 返回 Markdown（段落为正文、列表为 Markdown 列表、表格为 Markdown 表格）。

调用 `read("documents/0001-contract/0001-section/0001-block.md")` 的成功结果示例：

```json
{"ok":true,"path":"documents/0001-contract/0001-section/0001-block.md","text":"付款期限为30天。"}
```

调用 `read("index/index.json")` 返回：

```json
{"ok":false,"errors":[{"code":"BAD_PATH","message":"path escapes the document workspace: index/index.json"}]}
```

空路径、越界或对象缺失统一使用 `BAD_PATH`；其他普通异常使用通用 `errors` 结构。
