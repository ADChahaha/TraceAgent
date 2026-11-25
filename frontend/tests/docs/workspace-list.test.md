# workspace-list.test.tsx

- 无浏览器缓存也能列出服务端工作区，展示可读标题而非 UUID 并重新聚焦刷新：清空 localStorage，打开菜单后检查服务端 workspace 展示可读 `title`（缺失时回退 `Untitled workspace`）而非 UUID，模拟另一个标签页创建 workspace 后当前窗口 focus，验证重新读取并替换目录。
