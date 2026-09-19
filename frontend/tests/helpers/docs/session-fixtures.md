# session-fixtures.ts

`ready` 和 `running` 分别表示有资源的空闲会话与带首问的活跃会话。

`controlledStream` 构造真实 ReadableStream，提供 push/event/close 和 cancelled 观察点，供组件及连接测试控制快照、增量、断流和订阅释放。TextEncoder/TextDecoder 补齐 JSDOM 缺失的浏览器解码能力。
