# 文件下载与文档内容读取接口

本页属 [Backend API](../API.md)，定义会话级原文件下载、文档目录与引用原文读取接口。所有路径均绑定本会话资源引用，跨会话不可达。

## `GET /chat/sessions/{session_id}/blocks?key=...`

按引用 key 返回段落原文，供前端回溯答案中的证据链接（如 `[1](documents/0001-contract/0001-section/0001-block.md)`）：

```json
{"key":"documents/0001-contract/0001-section/0001-block.md","text":"付款期限为三十天。","found":true}
```

- `key` 为文档归档内的 `documents/...` 路径。
- `key` 不在归档内、会话无归档、会话缺失或空闲已回收均返回 404。

## `GET /chat/sessions/{session_id}/files/{resource_id}`

下载会话原始文件字节（raw），供前端预览或保存原件：

```text
200: application/octet-stream
Content-Disposition: attachment; filename*=UTF-8''%E5%90%88%E5%90%8C.pdf
```

- `resource_id` 来自资源引用列表中的 `raw` 行，由 `session_id` 隔离归属；会话缺失、资源不存在或非 raw 返回 404/422。

## `GET /chat/sessions/{session_id}/documents`

列出会话文档归档内的处理后 `.md` 文件，供前端浏览文档树：

```json
{"documents":[{"key":"documents/0001-合同/0001-付款期限为三十天.md","size":27}]}
```

- `key` 与 `/blocks` 统一使用 `documents/...` 路径，`size` 为字节数；未上传过文件时返回 404。

## `GET /chat/sessions/{session_id}/documents/full?key=...`

- `key` 可为一级文档目录（如 `documents/001-合同`）或该目录下具体引用块。
- 返回 `{"key":"documents/001-合同","blocks":[{"key":"documents/001-合同/001-开头.md","text":"..."}]}`，包含所选文档全部 Markdown 块并按路径数字顺序排列，不混入其他文档。
- 越界或非 `documents` 路径返回 422；缺少文档、归档或会话返回 404。

## `GET /chat/sessions/{session_id}/documents/content?key=...`

按归档 `key` 返回单个处理后 `.md` 文件全文：

```json
{"key":"documents/0001-合同/0001-付款期限为三十天.md","text":"付款期限为三十天。"}
```

- `key` 不在归档内返回 404。段落回溯用 `/blocks`，单文件读取用本接口，整篇文档连续阅读用 `/documents/full`。
