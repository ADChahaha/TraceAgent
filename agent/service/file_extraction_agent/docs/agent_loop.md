Iterable伪代码如下:
```python
while True:
    event = await message_queue.get()  # 从agent_loop的队列里取出内容
    if cancel_flag.is_set():  # 检查是否收到取消信号
        break
    yield event  # 将事件yield给SSE next()

```

Agent Loop 伪代码如下:
```python
history = [] # 存储历史消息
# 构造system prompt
system_prompt = build_system_prompt()
history.append({"role": "system", "content": system_prompt})
# 构建history messages
for message in messages:
    history.append(message)
while True:
    if cancel_flag.is_set():  # 检查是否收到取消信号
        break

    response = await client.chat.completions.create(
        model=model_config,
        messages=history,
        tools=tools,
        run_options=run_options,
    )
    # 将新消息放到queue
    await message_queue.put(response)
    # 加入history
    history.append({"role": "assistant", "content": response.choices[0].message.content})
    # 判断是否结束
    if response.choices[0].finish_reason == "stop":
        break
    # 判断是否是 tool 调用
    if response.choices[0].finish_reason == "tool_call":
        tool_response = call_tool(response.choices[0].message.tool_calls[0])
        if cancel_flag.is_set():  # 再次检查是否收到取消信号
            break
        history.append({"role": "tool", "content": tool_response})
        message_queue.put(tool_response)

```

Agent读取文档示意图
```mermaid
sequenceDiagram
    participant A as Agent Loop
    participant D as Document

    A->>D: fuzzy_search 检索有哪些符合内容的文件(未实现)
    D->>A: 返回符合条件的文件列表
    A->>D: ls文件，看看有哪些section
    D->>A: 返回section列表
    A->>D: read模型想要read的paragraph、table和list等内容
    D->>A: 返回对应内容
    A->>D: grep文件内搜索(精细匹配)，输入关键词
    D->>A: 返回符合条件的句子列表
    A->>D: inspect句子，作为输出引用
    D->>A: 返回句子内容和标识符
    A->>A: 模型输出结果，引用了paragraph级别或者inline级别的标识符
```