"use client";

import * as React from "react";
import { AlertCircle, FileUp, History, Loader2, Moon, SendHorizonal, Sun } from "lucide-react";
import { toast } from "sonner";

import {
  createTask as defaultCreateTask,
  getTaskSummary as defaultGetTaskSummary,
  listTasks as defaultListTasks
} from "@/lib/api";
import { parseJsonObject } from "@/lib/json";
import { applyStoredTheme, getStoredTheme, type AppTheme } from "@/lib/theme";
import {
  addRecentTask,
  getRecentTasks,
  syncRecentTaskSummaries,
  updateRecentTask,
  type RecentTask
} from "@/lib/task-store";
import type { Capabilities, TaskCreated, TaskSummary } from "@/lib/types";
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
  getTaskSummary?: (taskId: string) => Promise<TaskSummary>;
  listTasks?: () => Promise<TaskSummary[]>;
  onCreated?: (task: TaskCreated) => void;
}

const EMPTY_TASK_SPEC = {
  task_name: "",
  fields: []
};

const TERMINAL_STATUSES = new Set(["waiting_review", "completed", "rejected", "failed"]);
const POLL_INTERVAL_MS = 1500;
const MAX_POLL_ATTEMPTS = 120;

export function UploadWorkbench({
  capabilities,
  createTask = defaultCreateTask,
  getTaskSummary = defaultGetTaskSummary,
  listTasks = defaultListTasks,
  onCreated
}: UploadWorkbenchProps) {
  const [taskType, setTaskType] = React.useState("");
  const [taskSpec, setTaskSpec] = React.useState(JSON.stringify(EMPTY_TASK_SPEC, null, 2));
  const [metadata, setMetadata] = React.useState("{}");
  const [files, setFiles] = React.useState<File[]>([]);
  const [error, setError] = React.useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = React.useState(false);
  const [recentTasks, setRecentTasks] = React.useState<RecentTask[]>(() => getRecentTasks());
  const [theme, setTheme] = React.useState<AppTheme>(() => getStoredTheme());
  const pollTimeouts = React.useRef<ReturnType<typeof setTimeout>[]>([]);
  const mounted = React.useRef(true);

  React.useEffect(() => {
    applyStoredTheme(theme);
  }, [theme]);

  React.useEffect(() => {
    mounted.current = true;
    const trackedTimeouts = pollTimeouts.current;
    return () => {
      mounted.current = false;
      for (const timeout of trackedTimeouts) {
        clearTimeout(timeout);
      }
      trackedTimeouts.length = 0;
    };
  }, []);

  React.useEffect(() => {
    let cancelled = false;
    listTasks()
      .then((tasks) => {
        if (tasks.length > 0 && !cancelled && mounted.current) {
          setRecentTasks(syncRecentTaskSummaries(tasks));
        }
      })
      .catch(() => {
        // 最近任务列表可以继续使用本地缓存；连接错误由详情页或创建流程暴露。
      });
    return () => {
      cancelled = true;
    };
  }, [listTasks]);

  const refreshTaskSummary = React.useCallback(
    async (taskId: string) => {
      for (let attempt = 0; attempt <= MAX_POLL_ATTEMPTS; attempt += 1) {
        try {
          const summary = await getTaskSummary(taskId);
          if (!mounted.current) {
            return;
          }
          setRecentTasks(updateRecentTask(summary));
          if (isTaskTerminal(summary)) {
            return;
          }
        } catch {
          if (!mounted.current) {
            return;
          }
        }

        if (attempt < MAX_POLL_ATTEMPTS) {
          await waitForPollInterval(pollTimeouts);
        }
      }
    },
    [getTaskSummary]
  );

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    if (files.length === 0) {
      setError("请选择 PDF 文件");
      return;
    }
    if (files.some((file) => !isPdfFile(file))) {
      setError("第一版只支持 PDF 文件");
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
      void refreshTaskSummary(created.task_id);
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
        <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0 space-y-2">
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <FileUp className="h-4 w-4 text-muted-foreground" />
              <span>文档治理任务</span>
            </div>
            <h1 className="text-3xl font-semibold tracking-normal text-foreground">上传工作台</h1>
            <p className="max-w-2xl text-sm leading-6 text-muted-foreground">
              上传 PDF，显式提交字段 schema；任务创建后立即入队，右侧列表会跟随处理进度更新。
            </p>
          </div>
          <ThemeModeButton theme={theme} onThemeChange={setTheme} />
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
                <Label htmlFor="file">上传 PDF（可多选）</Label>
                <Input
                  id="file"
                  type="file"
                  multiple
                  accept=".pdf,application/pdf"
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
              POST /tasks 返回任务入队结果，处理状态通过右侧列表和任务详情刷新。
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
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant={isTaskTerminal(task) ? "secondary" : "outline"}>
                    {isTaskTerminal(task) ? "处理结果" : "处理中"}
                  </Badge>
                  <span className="text-xs text-muted-foreground">
                    {isTaskTerminal(task) ? getTaskResultLabel(task) : task.stage}
                  </span>
                </div>
                {task.error_message ? (
                  <p className="line-clamp-2 text-xs leading-5 text-destructive">
                    失败原因：{task.error_message}
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </aside>
    </div>
  );
}

function ThemeModeButton({
  theme,
  onThemeChange
}: {
  theme: AppTheme;
  onThemeChange: (theme: AppTheme) => void;
}) {
  const isDark = theme === "dark";
  return (
    <button
      type="button"
      className="theme-mode-button"
      aria-label="切换主题"
      title={isDark ? "切换到 Light theme" : "切换到 Dark theme"}
      onClick={() => onThemeChange(isDark ? "light" : "dark")}
    >
      {isDark ? <Moon className="h-3.5 w-3.5" aria-hidden="true" /> : <Sun className="h-3.5 w-3.5" aria-hidden="true" />}
      {isDark ? "Dark" : "Light"}
    </button>
  );
}

function isTaskTerminal(task: Pick<RecentTask, "status"> | TaskSummary): boolean {
  return TERMINAL_STATUSES.has(task.status);
}

function getTaskResultLabel(task: RecentTask): string {
  if (task.route) {
    return task.route;
  }
  if (task.status === "failed") {
    return "failed";
  }
  return task.status;
}

function isPdfFile(file: File): boolean {
  return file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
}

function waitForPollInterval(
  pollTimeouts: React.MutableRefObject<ReturnType<typeof setTimeout>[]>
): Promise<void> {
  return new Promise((resolve) => {
    const timeout = setTimeout(() => {
      const index = pollTimeouts.current.indexOf(timeout);
      if (index >= 0) {
        pollTimeouts.current.splice(index, 1);
      }
      resolve();
    }, POLL_INTERVAL_MS);
    pollTimeouts.current.push(timeout);
  });
}
