# `home-workspace.test.tsx`

这组测试覆盖首页工作台和 Next 路由之间的衔接。首页仍由 `HomeWorkspace` 挂载 `UploadWorkbench`，但创建任务成功后要立即进入新任务详情页，让用户直接看到处理中的任务。

## 测试链路

```text
用户在首页选择 PDF 并提交 task_spec
  -> UploadWorkbench 调用 createTask
  -> backend 返回 task_id
  -> HomeWorkspace 收到 onCreated 回调
  -> next/navigation router.push("/tasks/{task_id}")
```

## 测试函数

- `创建任务成功后直接跳到新任务详情页`：验证首页创建任务成功后会调用 Next router，把页面切到 `/tasks/{task_id}`，而不是停留在首页等待用户手动点击左侧任务。
