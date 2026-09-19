# workspace-list.test.tsx

- 无浏览器缓存也能列出服务端工作区，重新聚焦刷新列表：清空 localStorage，打开菜单后检查服务端 workspace 链接，模拟另一个标签页创建 workspace 后当前窗口 focus，验证重新读取并替换目录。
