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
  createTaskInput as defaultCreateTaskInput,
  createTask as defaultCreateTask,
  getTaskSummary as defaultGetTaskSummary,
  listTasks as defaultListTasks
} from "@/lib/api";
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
import {
  DEFAULT_LEFT_PANEL_WIDTH,
  LeftSidebarResizeHandle,
  useLeftSidebarResize
} from "@/components/sidebar-resize";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

export interface UploadWorkbenchProps {
  createTask?: (formData: FormData) => Promise<TaskCreated>;
  createTaskInput?: (taskId: string, content: string) => Promise<unknown>;
  getTaskSummary?: (taskId: string) => Promise<TaskSummary>;
  listTasks?: () => Promise<TaskSummary[]>;
  onCreated?: (task: TaskCreated) => void;
}

const IDLE_STATUSES = new Set(["ready", "failed"]);
const POLL_INTERVAL_MS = 1500;
const MAX_POLL_ATTEMPTS = 120;

export function UploadWorkbench({
  createTask = defaultCreateTask,
  createTaskInput = defaultCreateTaskInput,
  getTaskSummary = defaultGetTaskSummary,
  listTasks = defaultListTasks,
  onCreated
}: UploadWorkbenchProps) {
  const [question, setQuestion] = React.useState("");
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
  const { leftPanelWidth, resizeLeftPanelByKeyboard, startLeftPanelResize } = useLeftSidebarResize();
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
          if (isTaskIdle(summary)) {
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
    await submitQuestion();
  }

  async function submitQuestion() {
    setError(null);

    if (files.length === 0) {
      setError("Select at least one PDF file");
      return;
    }
    if (files.some((file) => !isPdfFile(file))) {
      setError("Only PDF files are supported");
      return;
    }

    const trimmedQuestion = question.trim();
    if (!trimmedQuestion) {
      setError("Enter a question");
      return;
    }

    const formData = new FormData();
    for (const file of files) {
      formData.append("files", file);
    }

    setIsSubmitting(true);
    try {
      const created = await createTask(formData);
      addRecentTask(created);
      onCreated?.(created);
      void createTaskInput(created.task_id, trimmedQuestion).catch((inputError) => {
        const message = inputError instanceof Error ? inputError.message : "Failed to submit the first question";
        updateRecentTask({ ...created, status: "failed", stage: "done", error_message: message });
        toast.error("Failed to submit the first question", { description: message });
      });
      void refreshTaskSummary(created.task_id);
      toast.success("Task created", {
        description: `${created.task_id} / ${created.status}`
      });
    } catch (submitError) {
      const message = submitError instanceof Error ? submitError.message : "Failed to create task";
      setError(message);
      toast.error("Failed to create task", { description: message });
    } finally {
      setIsSubmitting(false);
    }
  }

  function handleQuestionKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (!shouldSubmitComposerOnKeyDown(event) || isSubmitting) {
      return;
    }
    event.preventDefault();
    void submitQuestion();
  }

  function handleFileChange(event: React.ChangeEvent<HTMLInputElement>) {
    const selectedFiles = Array.from(event.currentTarget.files ?? []);
    setFiles((currentFiles) => mergeSelectedFiles(currentFiles, selectedFiles));
    event.currentTarget.value = "";
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
      aria-label="Home task workbench"
      className="home-task-workbench replay-review-root replay-review-root-fullscreen"
      data-left-panel-open={isLeftPanelOpen ? "true" : "false"}
      style={{ "--replay-left-panel-width": `${leftPanelWidth || DEFAULT_LEFT_PANEL_WIDTH}px` } as React.CSSProperties}
    >
      <div className="replay-topbar" aria-label="Task workbench top bar">
        <div className="replay-topbar-main">
          <button
            type="button"
            className="replay-topbar-back"
            aria-label={isLeftPanelOpen ? "Close sidebar" : "Open sidebar"}
            title={isLeftPanelOpen ? "Close sidebar" : "Open sidebar"}
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
          <aside className="replay-task-sidebar overflow-hidden bg-background" aria-label="Tasks sidebar">
            <TaskSidebar tasks={recentTasks} />
          </aside>
        ) : null}
        {isLeftPanelOpen ? (
          <LeftSidebarResizeHandle
            width={leftPanelWidth}
            onPointerDown={startLeftPanelResize}
            onKeyDown={resizeLeftPanelByKeyboard}
          />
        ) : null}

        <main className="home-agent-panel-slot" aria-label="Agent task workspace">
          <section className="home-new-task-center">
            <h1>What should we ask these documents?</h1>
            <form className="home-task-composer" aria-label="Create task composer" onSubmit={handleSubmit}>
              <input
                ref={fileInputRef}
                type="file"
                multiple
                accept=".pdf,application/pdf"
                aria-label="PDF file input"
                className="sr-only"
                onChange={handleFileChange}
              />
              <Textarea
                aria-label="QA question input"
                value={question}
                onChange={(event) => {
                  setQuestion(event.target.value);
                  setError(null);
                }}
                onKeyDown={handleQuestionKeyDown}
                placeholder="Ask a question about the uploaded PDFs"
                spellCheck={true}
                className="home-task-spec-input"
              />
              {error ? (
                <div className="home-task-composer-error" role="alert">
                  <AlertCircle className="h-4 w-4" aria-hidden="true" />
                  <span>{error}</span>
                </div>
              ) : null}
              {files.length > 0 ? (
                <div className="home-task-file-strip" aria-label="Selected files">
                  {files.map((file) => (
                    <span key={`${file.name}-${file.size}`} className="home-task-file-chip">
                      <FileText className="h-3.5 w-3.5" aria-hidden="true" />
                      <span className="home-task-file-name">{file.name}</span>
                      <button
                        type="button"
                        className="home-task-file-remove"
                        aria-label={`Remove ${file.name}`}
                        title={`Remove ${file.name}`}
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
                    aria-label="Add PDF"
                    title="Add PDF"
                    onClick={() => fileInputRef.current?.click()}
                  >
                    <Paperclip className="h-4 w-4" />
                  </Button>
                  <span>{files.length > 0 ? `${files.length} PDF${files.length > 1 ? "s" : ""}` : "PDF"}</span>
                </div>
                <Button type="submit" size="icon" aria-label="Upload documents and ask" title="Upload documents and ask" disabled={isSubmitting}>
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

function shouldSubmitComposerOnKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>): boolean {
  return event.key === "Enter" && !event.shiftKey && !event.altKey && !event.ctrlKey && !event.metaKey && !event.nativeEvent.isComposing;
}

function TaskSidebar({ tasks }: { tasks: RecentTask[] }) {
  return (
    <div className="replay-task-sidebar-inner">
      <div className="replay-task-sidebar-header">
        <span className="replay-task-sidebar-label">Tasks</span>
        <Link className="replay-new-task-link" href="/" aria-label="New task">
          <Plus className="h-3.5 w-3.5" aria-hidden="true" />
          New task
        </Link>
      </div>
      <div className="replay-task-list">
        {tasks.length === 0 ? (
          <div className="replay-task-empty">No tasks yet.</div>
        ) : (
          tasks.map((task) => (
            <Link key={task.task_id} className="replay-task-item" href={`/tasks/${task.task_id}`}>
              <span className="replay-task-id">{task.task_id}</span>
              <span className="replay-task-meta">
                {isTaskIdle(task) ? (
                  <CheckCircle2 className="home-task-inline-icon" aria-hidden="true" />
                ) : (
                  <Clock3 className="home-task-inline-icon" aria-hidden="true" />
                )}
                {task.status} / {task.stage}
              </span>
              <span className="replay-task-status-detail">
                {isTaskIdle(task) ? getTaskResultLabel(task) : task.stage}
              </span>
              {task.error_message ? (
                <span className="replay-task-error">{task.error_message}</span>
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
      aria-label="Toggle theme"
      title={isDark ? "Switch to light theme" : "Switch to dark theme"}
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

function isTaskIdle(task: Pick<RecentTask, "status" | "stream" | "active_turn_id"> | TaskSummary): boolean {
  return IDLE_STATUSES.has(task.status) && task.stream?.state !== "running" && !task.active_turn_id;
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

function mergeSelectedFiles(currentFiles: File[], selectedFiles: File[]): File[] {
  if (selectedFiles.length === 0) {
    return currentFiles;
  }
  const seen = new Set(currentFiles.map(getFileSignature));
  const merged = [...currentFiles];
  for (const file of selectedFiles) {
    const signature = getFileSignature(file);
    if (seen.has(signature)) {
      continue;
    }
    seen.add(signature);
    merged.push(file);
  }
  return merged;
}

function getFileSignature(file: File): string {
  return `${file.name}::${file.size}::${file.lastModified}::${file.type}`;
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
