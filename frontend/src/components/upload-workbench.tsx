"use client";

import * as React from "react";
import { AlertCircle, FileUp, History, Loader2, SendHorizonal } from "lucide-react";
import { toast } from "sonner";

import { createTask as defaultCreateTask } from "@/lib/api";
import { parseJsonObject } from "@/lib/json";
import { addRecentTask, getRecentTasks, type RecentTask } from "@/lib/task-store";
import type { Capabilities, TaskCreated } from "@/lib/types";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";

export interface UploadWorkbenchProps {
  capabilities: Capabilities;
  createTask?: (formData: FormData) => Promise<TaskCreated>;
  onCreated?: (task: TaskCreated) => void;
}

const TASK_SPEC_TEMPLATE = {
  task_name: "civilized_dormitory",
  fields: [
    {
      field_name: "document_title",
      display_name: "文档标题",
      type: "string",
      required: true
    },
    {
      field_name: "building_name",
      display_name: "楼栋",
      type: "string",
      required: true
    },
    {
      field_name: "civilized_dormitory_rooms",
      display_name: "文明寝室房间号",
      type: "string",
      required: true,
      cross_field_hints: [
        "只抽取表格里“模范/文明”列明确标注为“文明寝室”的房间号。",
        "多个房间号请按出现顺序输出为中文逗号分隔字符串，例如 212、214、302。"
      ]
    },
    {
      field_name: "civilized_dormitory_count",
      display_name: "文明寝室数量",
      type: "string",
      required: true,
      cross_field_hints: ["数量应与文明寝室房间号列表对应。"]
    }
  ]
};

export function UploadWorkbench({
  capabilities,
  createTask = defaultCreateTask,
  onCreated
}: UploadWorkbenchProps) {
  const [taskType, setTaskType] = React.useState("civilized_dormitory");
  const [taskSpec, setTaskSpec] = React.useState(JSON.stringify(TASK_SPEC_TEMPLATE, null, 2));
  const [metadata, setMetadata] = React.useState("{}");
  const [files, setFiles] = React.useState<File[]>([]);
  const [error, setError] = React.useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = React.useState(false);
  const [recentTasks, setRecentTasks] = React.useState<RecentTask[]>(() => getRecentTasks());

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    if (files.length === 0) {
      setError("请选择 PDF 或 DOCX 文件");
      return;
    }
    if (!taskType.trim()) {
      setError("task_type 不能为空");
      return;
    }

    const parsedTaskSpec = parseJsonObject(taskSpec, "task_spec");
    if (!parsedTaskSpec.ok) {
      setError(parsedTaskSpec.error);
      return;
    }
    const parsedMetadata = parseJsonObject(metadata || "{}", "metadata");
    if (!parsedMetadata.ok) {
      setError(parsedMetadata.error);
      return;
    }

    const formData = new FormData();
    for (const file of files) {
      formData.append("files", file);
    }
    formData.set("task_type", taskType.trim());
    formData.set("task_spec", JSON.stringify(parsedTaskSpec.value));
    if (Object.keys(parsedMetadata.value).length > 0) {
      formData.set("metadata", JSON.stringify(parsedMetadata.value));
    }

    setIsSubmitting(true);
    try {
      const created = await createTask(formData);
      setRecentTasks(addRecentTask(created));
      toast.success("任务已创建", {
        description: `${created.task_id} / ${created.status}`
      });
      onCreated?.(created);
    } catch (submitError) {
      const message = submitError instanceof Error ? submitError.message : "创建任务失败";
      setError(message);
      toast.error("创建任务失败", { description: message });
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="grid min-h-[calc(100svh-4rem)] gap-8 lg:grid-cols-[minmax(0,1fr)_20rem]">
      <main className="min-w-0">
        <div className="mb-6 flex flex-col gap-2">
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <FileUp className="h-4 w-4 text-primary" />
            <span>文档治理任务</span>
          </div>
          <h1 className="text-3xl font-semibold tracking-normal text-foreground">上传工作台</h1>
          <p className="max-w-2xl text-sm leading-6 text-muted-foreground">
            上传一个或多个 PDF/DOCX，显式提交字段 schema，由 backend 同步完成抽取、路由、复核和审计链路。
          </p>
        </div>

        <Alert className="mb-6">
          <AlertCircle className="absolute left-4 top-4 h-4 w-4 text-primary" />
          <AlertTitle className="pl-6">backend 能力边界</AlertTitle>
          <AlertDescription className="pl-6">
            <span>支持文件：{capabilities.supported_file_types.join(" / ")}</span>
            <span className="mx-2 text-muted-foreground">·</span>
            <span>
              {capabilities.features.external_task_spec
                ? "task_spec 必须由前端显式提交"
                : "backend 提供默认 task_spec"}
            </span>
            {capabilities.features.multiple_files ? (
              <>
                <span className="mx-2 text-muted-foreground">·</span>
                <span>支持多文件任务</span>
                <span className="mx-2 text-muted-foreground">·</span>
                <span>multipart 字段：files（可重复）</span>
                <span className="mx-2 text-muted-foreground">·</span>
                <span>旧版 file 字段仅后端兼容，前端固定提交 files。</span>
              </>
            ) : null}
          </AlertDescription>
        </Alert>

        <form onSubmit={handleSubmit} className="space-y-6">
          <div className="grid gap-5 md:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
            <div className="space-y-5">
              <div className="space-y-2">
                <Label htmlFor="file">上传文件（可多选）</Label>
                <Input
                  id="file"
                  type="file"
                  multiple
                  accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                  onChange={(event) =>
                    setFiles(Array.from(event.currentTarget.files ?? []))
                  }
                />
                {files.length > 0 ? (
                  <p className="text-xs text-muted-foreground">
                    已选择 {files.length} 个文件：{files.map((item) => item.name).join("、")}
                  </p>
                ) : (
                  <p className="text-xs text-muted-foreground">
                    按住 Shift 或 Command/Ctrl 可一次选择多个文件；提交时会写入重复 files 字段。
                  </p>
                )}
              </div>
              <div className="space-y-2">
                <Label htmlFor="task_type">task_type</Label>
                <Input
                  id="task_type"
                  value={taskType}
                  onChange={(event) => setTaskType(event.target.value)}
                  placeholder="civilized_dormitory"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="metadata">metadata JSON</Label>
                <Textarea
                  id="metadata"
                  value={metadata}
                  onChange={(event) => setMetadata(event.target.value)}
                  className="min-h-28 font-mono text-xs leading-5"
                />
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="task_spec">task_spec JSON</Label>
              <Textarea
                id="task_spec"
                value={taskSpec}
                onChange={(event) => setTaskSpec(event.target.value)}
                className="min-h-[22rem] font-mono text-xs leading-5"
              />
            </div>
          </div>

          {error ? (
            <Alert variant="destructive">
              <AlertTitle>提交被拦截</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          ) : null}

          <div className="flex flex-wrap items-center gap-3">
            <Button type="submit" disabled={isSubmitting}>
              {isSubmitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <SendHorizonal />}
              创建任务
            </Button>
            <span className="text-xs text-muted-foreground">
              POST /tasks 会同步返回 completed、waiting_review、rejected 或 failed。
            </span>
          </div>
        </form>
      </main>

      <aside className="border-l border-border pl-6">
        <div className="mb-3 flex items-center gap-2">
          <History className="h-4 w-4 text-muted-foreground" />
          <h2 className="text-sm font-medium">最近任务</h2>
        </div>
        <Separator className="mb-3" />
        {recentTasks.length === 0 ? (
          <p className="text-sm leading-6 text-muted-foreground">本机浏览器暂无任务记录。</p>
        ) : (
          <ul className="space-y-3">
            {recentTasks.map((task) => (
              <li key={task.task_id} className="space-y-1 text-sm">
                <a className="font-medium text-foreground hover:text-primary" href={`/tasks/${task.task_id}`}>
                  {task.task_id}
                </a>
                <div className="flex items-center gap-2">
                  <Badge variant="outline">{task.status}</Badge>
                  <span className="text-xs text-muted-foreground">{task.stage}</span>
                </div>
              </li>
            ))}
          </ul>
        )}
      </aside>
    </div>
  );
}
