"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import {
  createTaskEventSource as defaultCreateTaskEventSource,
  listTasks as defaultListTasks,
  loadTaskDetail as defaultLoadTaskDetail,
  parseTaskEventMessage,
} from "@/lib/api";
import { getRecentTasks, syncRecentTaskSummaries, updateRecentTask, type RecentTask } from "@/lib/task-store";
import type {
  TaskDetailData,
  TaskEvent,
  TaskSummary
} from "@/lib/types";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { ReplayReview } from "@/components/replay-review";

const DETAIL_REFRESH_INTERVAL_MS = 1500;
const TERMINAL_STATUSES = new Set(["completed", "failed"]);
const TASK_EVENT_NAMES = [
  "message",
  "task.created",
  "task.stage_changed",
  "document.processed",
  "agent.event",
  "field.written",
  "task.completed",
  "task.failed",
];

export interface TaskDetailProps {
  taskId: string;
  initialSummary?: TaskSummary;
  loadTaskDetail?: (taskId: string) => Promise<TaskDetailData>;
  listTasks?: () => Promise<TaskSummary[]>;
  createTaskEventSource?: (taskId: string, afterSeq?: number) => EventSource;
}

export function TaskDetail({
  taskId,
  initialSummary,
  loadTaskDetail = defaultLoadTaskDetail,
  listTasks = defaultListTasks,
  createTaskEventSource = defaultCreateTaskEventSource,
}: TaskDetailProps) {
  const [detail, setDetail] = React.useState<TaskDetailData | null>(
    initialSummary
      ? { summary: initialSummary, result: null, trace: null, replay: null, audit: null }
      : null
  );
  const [isLoading, setIsLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [recentTasks, setRecentTasks] = React.useState<RecentTask[]>(() => getRecentTasks());
  const [liveActions, setLiveActions] = React.useState<TaskEvent[]>([]);
  const eventCursorRef = React.useRef({
    taskId,
    seq: 0,
  });

  const refresh = React.useCallback(async () => {
    setError(null);
    try {
      const loaded = await loadTaskDetail(taskId);
      setDetail(loaded);
      setRecentTasks(updateRecentTask(loaded.summary));
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "加载任务失败");
    } finally {
      setIsLoading(false);
    }
  }, [loadTaskDetail, taskId]);

  React.useEffect(() => {
    // 初次进入详情页需要从 backend 同步任务快照。
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refresh();
  }, [refresh]);

  React.useEffect(() => {
    let cancelled = false;
    listTasks()
      .then((tasks) => {
        if (!cancelled && tasks.length > 0) {
          setRecentTasks(syncRecentTaskSummaries(tasks));
        }
      })
      .catch(() => {
        // 左侧任务栏可以继续使用本地缓存；详情加载错误由主流程暴露。
      });
    return () => {
      cancelled = true;
    };
  }, [listTasks]);

  const summary = detail?.summary ?? initialSummary;
  const shouldKeepRefreshing = summary ? !isTaskTerminal(summary) : false;

  React.useEffect(() => {
    if (!shouldKeepRefreshing || typeof window === "undefined") {
      return;
    }
    eventCursorRef.current = { taskId, seq: 0 };
    const eventSource = createTaskEventSource(taskId, 0);
    const handleMessage = (message: MessageEvent<string>) => {
      const event = parseTaskEventMessage(message);
      if (!event) {
        return;
      }
      eventCursorRef.current = {
        taskId,
        seq: Math.max(eventCursorRef.current.seq, event.seq),
      };
      if (event.type === "task.stage_changed") {
        setDetail((current) =>
          current
            ? {
                ...current,
                summary: {
                  ...current.summary,
                  status: event.status as TaskSummary["status"],
                  stage: event.stage as TaskSummary["stage"],
                  stream: {
                    state: "running",
                    last_event_seq: event.seq,
                  },
                },
              }
            : current,
        );
      }
      if (event.type === "agent.event") {
        setLiveActions((current) => appendLiveTaskEvent(current, event));
        const payload = event.payload && typeof event.payload === "object" ? event.payload as Record<string, unknown> : {};
        if (payload.type === "source_indexed") {
          void refresh();
        }
      }
      if (event.type === "task.completed" || event.type === "task.failed") {
        void refresh();
        eventSource.close();
      }
    };
    TASK_EVENT_NAMES.forEach((eventName) => {
      eventSource.addEventListener(eventName, handleMessage);
    });
    eventSource.onerror = () => {
      eventSource.close();
    };
    return () => {
      TASK_EVENT_NAMES.forEach((eventName) => {
        eventSource.removeEventListener(eventName, handleMessage);
      });
      eventSource.close();
    };
  }, [createTaskEventSource, refresh, shouldKeepRefreshing, taskId]);

  React.useEffect(() => {
    if (!shouldKeepRefreshing || liveActions.length > 0) {
      return;
    }
    const interval = window.setInterval(() => {
      void refresh();
    }, DETAIL_REFRESH_INTERVAL_MS);
    return () => {
      window.clearInterval(interval);
    };
  }, [liveActions.length, refresh, shouldKeepRefreshing]);

  return (
    <main aria-label="任务详情全屏工作台" className="task-detail-fullscreen-shell">
      {!detail?.replay ? (
        <div className="replay-topbar" aria-label="任务详情顶部工具栏">
          <div className="replay-topbar-main">
            <Link href="/" className="replay-topbar-back" aria-label="返回首页">
              <ArrowLeft className="h-4 w-4" aria-hidden="true" />
            </Link>
            <div className="replay-topbar-title">
              {`${taskId} / no replay`}
            </div>
          </div>
          <div className="replay-topbar-status">
            {summary ? <StatusBadge status={summary.status} /> : null}
          </div>
        </div>
      ) : null}

      {error ? (
        <Alert variant="destructive" className="task-detail-alert">
          <AlertTitle>任务加载失败</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      {summary?.status === "failed" && summary.error_message ? (
        <Alert variant="destructive" className="task-detail-alert">
          <AlertTitle>任务失败</AlertTitle>
          <AlertDescription>{summary.error_message}</AlertDescription>
        </Alert>
      ) : null}

      {isLoading && !detail ? (
        <div className="flex min-h-screen items-center justify-center text-sm text-muted-foreground">正在加载任务详情...</div>
      ) : null}

      {detail ? (
        <ReplayReview
          taskId={taskId}
          summary={summary}
          replay={detail.replay}
          recentTasks={recentTasks}
          finalFields={detail.result?.fields ?? []}
          liveActions={liveActions}
        />
      ) : null}
    </main>
  );
}

function isTaskTerminal(summary: TaskSummary): boolean {
  return TERMINAL_STATUSES.has(summary.status) || summary.stream?.state === "ended";
}

function appendLiveTaskEvent(current: TaskEvent[], event: TaskEvent): TaskEvent[] {
  if (current.some((item) => item.seq === event.seq)) {
    return current;
  }
  return [...current, event].sort((left, right) => left.seq - right.seq);
}

function StatusBadge({ status }: { status: TaskSummary["status"] }) {
  if (status === "completed") {
    return <Badge variant="success">{status}</Badge>;
  }
  if (status === "processing" || status === "pending") {
    return <Badge variant="warning">{status}</Badge>;
  }
  if (status === "failed") {
    return <Badge variant="destructive">{status}</Badge>;
  }
  return <Badge variant="secondary">{status}</Badge>;
}
