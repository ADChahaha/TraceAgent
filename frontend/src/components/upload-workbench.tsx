"use client";

import * as React from "react";
import Link from "next/link";
import {
  AlertCircle,
  CheckCircle2,
  Clock3,
  FileText,
  Loader2,
  Moon,
  Paperclip,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  SendHorizonal,
  Sun,
  X
} from "lucide-react";
import { toast } from "sonner";

import {
  createTask as defaultCreateTask,
  getTaskSummary as defaultGetTaskSummary,
  listTasks as defaultListTasks
} from "@/lib/api";
import { parseJsonObject } from "@/lib/json";
import {
  applyStoredTheme,
  getServerThemeSnapshot,
  getThemeSnapshot,
  subscribeTheme,
  type AppTheme
} from "@/lib/theme";
import {
  addRecentTask,
  getRecentTasksSnapshot,
  getServerRecentTasksSnapshot,
  subscribeRecentTasks,
  syncRecentTaskSummaries,
  updateRecentTask,
  type RecentTask
} from "@/lib/task-store";
import type { TaskCreated, TaskSummary } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

export interface UploadWorkbenchProps {
  createTask?: (formData: FormData) => Promise<TaskCreated>;
  getTaskSummary?: (taskId: string) => Promise<TaskSummary>;
  listTasks?: () => Promise<TaskSummary[]>;
  onCreated?: (task: TaskCreated) => void;
}

const DEFAULT_TASK_SPEC = {
  task_name: "",
  fields: []
};

const TERMINAL_STATUSES = new Set(["completed", "failed"]);
const POLL_INTERVAL_MS = 1500;
const MAX_POLL_ATTEMPTS = 120;

export function UploadWorkbench({
  createTask = defaultCreateTask,
  getTaskSummary = defaultGetTaskSummary,
  listTasks = defaultListTasks,
  onCreated
}: UploadWorkbenchProps) {
  const [taskSpec, setTaskSpec] = React.useState(JSON.stringify(DEFAULT_TASK_SPEC, null, 2));
  const [files, setFiles] = React.useState<File[]>([]);
  const [error, setError] = React.useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = React.useState(false);
  const recentTasks = React.useSyncExternalStore(
    subscribeRecentTasks,
    getRecentTasksSnapshot,
    getServerRecentTasksSnapshot,
  );
  const theme = React.useSyncExternalStore(subscribeTheme, getThemeSnapshot, getServerThemeSnapshot);
  const [isLeftPanelOpen, setIsLeftPanelOpen] = React.useState(true);
  const fileInputRef = React.useRef<HTMLInputElement | null>(null);
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
          syncRecentTaskSummaries(tasks);
        }
      })
      .catch(() => {
        // 首页仍然可以用本地 recent tasks 创建新任务；列表连接错误不阻断 composer。
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
          updateRecentTask(summary);
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

    const parsedTaskSpec = parseJsonObject(taskSpec, "task_spec");
    if (!parsedTaskSpec.ok) {
      setError(parsedTaskSpec.error);
      return;
    }
    const taskName = parsedTaskSpec.value.task_name;
    if (typeof taskName !== "string" || taskName.trim() === "") {
      setError("task_spec.task_name 不能为空");
      return;
    }

    const formData = new FormData();
    for (const file of files) {
      formData.append("files", file);
    }
    formData.set("task_type", taskName.trim());
    formData.set("task_spec", JSON.stringify(parsedTaskSpec.value));

    setIsSubmitting(true);
    try {
      const created = await createTask(formData);
      addRecentTask(created);
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

  function handleFileChange(event: React.ChangeEvent<HTMLInputElement>) {
    setFiles(Array.from(event.currentTarget.files ?? []));
    setError(null);
  }

  function removeFile(fileToRemove: File) {
    setFiles((currentFiles) => currentFiles.filter((file) => file !== fileToRemove));
    setError(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  }

  return (
    <section
      aria-label="首页任务工作台"
      className="home-task-workbench replay-review-root replay-review-root-fullscreen"
      data-left-panel-open={isLeftPanelOpen ? "true" : "false"}
    >
      <div className="replay-topbar" aria-label="任务工作台顶部工具栏">
        <div className="replay-topbar-main">
          <button
            type="button"
            className="replay-topbar-back"
            aria-label={isLeftPanelOpen ? "关闭任务栏" : "打开任务栏"}
            title={isLeftPanelOpen ? "关闭任务栏" : "打开任务栏"}
            onClick={() => setIsLeftPanelOpen((current) => !current)}
          >
            {isLeftPanelOpen ? (
              <PanelLeftClose className="h-4 w-4" aria-hidden="true" />
            ) : (
              <PanelLeftOpen className="h-4 w-4" aria-hidden="true" />
            )}
          </button>
          <div className="replay-topbar-title">Agent Gate / New task</div>
        </div>
        <div className="replay-topbar-status">
          <ThemeModeButton theme={theme} onThemeChange={applyStoredTheme} />
        </div>
      </div>

      <div className="home-task-stage">
        {isLeftPanelOpen ? (
          <aside className="replay-task-sidebar overflow-hidden bg-background" aria-label="任务栏">
            <TaskSidebar tasks={recentTasks} />
          </aside>
        ) : null}

        <main className="home-agent-panel-slot" aria-label="Agent 任务工作区">
          <section className="home-new-task-center">
            <h1>What task should we run in agent_gate?</h1>
            <form className="home-task-composer" aria-label="创建任务对话框" onSubmit={handleSubmit}>
              <input
                ref={fileInputRef}
                type="file"
                multiple
                accept=".pdf,application/pdf"
                aria-label="PDF 文件输入"
                className="sr-only"
                onChange={handleFileChange}
              />
              <Textarea
                aria-label="task_spec 输入框"
                value={taskSpec}
                onChange={(event) => {
                  setTaskSpec(event.target.value);
                  setError(null);
                }}
                placeholder="Paste task_spec JSON"
                spellCheck={false}
                className="home-task-spec-input"
              />
              {error ? (
                <div className="home-task-composer-error" role="alert">
                  <AlertCircle className="h-4 w-4" aria-hidden="true" />
                  <span>{error}</span>
                </div>
              ) : null}
              {files.length > 0 ? (
                <div className="home-task-file-strip" aria-label="已选择文件">
                  {files.map((file) => (
                    <span key={`${file.name}-${file.size}`} className="home-task-file-chip">
                      <FileText className="h-3.5 w-3.5" aria-hidden="true" />
                      <span className="home-task-file-name">{file.name}</span>
                      <button
                        type="button"
                        className="home-task-file-remove"
                        aria-label={`移除 ${file.name}`}
                        title={`移除 ${file.name}`}
                        onClick={() => removeFile(file)}
                      >
                        <X className="h-3 w-3" aria-hidden="true" />
                      </button>
                    </span>
                  ))}
                </div>
              ) : null}
              <div className="home-task-composer-actions">
                <div className="home-task-composer-left-actions">
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    aria-label="添加 PDF"
                    title="添加 PDF"
                    onClick={() => fileInputRef.current?.click()}
                  >
                    <Paperclip className="h-4 w-4" />
                  </Button>
                  <span>{files.length > 0 ? `${files.length} PDF` : "PDF"}</span>
                </div>
                <Button type="submit" size="icon" aria-label="发送 task_spec 创建任务" title="发送 task_spec 创建任务" disabled={isSubmitting}>
                  {isSubmitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <SendHorizonal className="h-4 w-4" />}
                </Button>
              </div>
            </form>
          </section>
        </main>

      </div>
    </section>
  );
}

function TaskSidebar({ tasks }: { tasks: RecentTask[] }) {
  return (
    <div className="replay-task-sidebar-inner">
      <div className="replay-task-sidebar-header">
        <span className="replay-task-sidebar-label">Tasks</span>
        <Link className="replay-new-task-link" href="/" aria-label="新任务">
          <Plus className="h-3.5 w-3.5" aria-hidden="true" />
          新任务
        </Link>
      </div>
      <div className="replay-task-list">
        {tasks.length === 0 ? (
          <div className="replay-task-empty">暂无任务。</div>
        ) : (
          tasks.map((task) => (
            <Link key={task.task_id} className="replay-task-item" href={`/tasks/${task.task_id}`}>
              <span className="replay-task-id">{task.task_id}</span>
              <span className="replay-task-meta">
                {isTaskTerminal(task) ? (
                  <CheckCircle2 className="home-task-inline-icon" aria-hidden="true" />
                ) : (
                  <Clock3 className="home-task-inline-icon" aria-hidden="true" />
                )}
                {isTaskTerminal(task) ? "处理结果" : "处理中"}
              </span>
              <span className="replay-task-status-detail">
                {isTaskTerminal(task) ? getTaskResultLabel(task) : task.stage}
              </span>
              {task.error_message ? (
                <span className="replay-task-error">失败原因：{task.error_message}</span>
              ) : null}
            </Link>
          ))
        )}
      </div>
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
      {isDark ? (
        <Moon className="h-3.5 w-3.5" aria-hidden="true" />
      ) : (
        <Sun className="h-3.5 w-3.5" aria-hidden="true" />
      )}
      {isDark ? "Dark" : "Light"}
    </button>
  );
}

function isTaskTerminal(task: Pick<RecentTask, "status"> | TaskSummary): boolean {
  return TERMINAL_STATUSES.has(task.status);
}

function getTaskResultLabel(task: RecentTask): string {
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
