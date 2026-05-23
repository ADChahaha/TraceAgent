# `home-workspace.test.tsx`

这组测试覆盖首页工作台和 Next 路由之间的衔接。首页仍由 `HomeWorkspace` 挂载 `UploadWorkbench`，但创建 QA task 后会先提交首问，再跳转到任务详情页。

## 测试链路

```text
用户在首页选择 PDF 并输入首问
  -> UploadWorkbench 通过英文 UI label 找到 PDF 输入框和提交按钮
  -> UploadWorkbench 调用 createTask
  -> backend 返回 task_id
  -> UploadWorkbench 调用 createTaskInput(task_id, question)
  -> HomeWorkspace 收到 onCreated 回调
  -> next/navigation router.push("/tasks/{task_id}")
```

## 测试函数

- `创建 QA task 并提交首问后直接跳到新任务详情页`：验证首页会完成“上传文档 -> 提交首问 -> 跳转详情”的完整链路。
