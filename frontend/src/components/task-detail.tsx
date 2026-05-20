"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import {
  listTasks as defaultListTasks,
  loadTaskDetail as defaultLoadTaskDetail,
} from "@/lib/api";
import { getRecentTasks, syncRecentTaskSummaries, updateRecentTask, type RecentTask } from "@/lib/task-store";
import type {
  TaskDetailData,
  TaskSummary
} from "@/lib/types";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { ReplayReview } from "@/components/replay-review";

export interface TaskDetailProps {
  taskId: string;
  initialSummary?: TaskSummary;
  loadTaskDetail?: (taskId: string) => Promise<TaskDetailData>;
  listTasks?: () => Promise<TaskSummary[]>;
}

export function TaskDetail({
  taskId,
  initialSummary,
  loadTaskDetail = defaultLoadTaskDetail,
  listTasks = defaultListTasks,
}: TaskDetailProps) {
  const [detail, setDetail] = React.useState<TaskDetailData | null>(
    initialSummary
      ? { summary: initialSummary, result: null, trace: null, replay: null, audit: null }
      : null
  );
  const [isLoading, setIsLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [recentTasks, setRecentTasks] = React.useState<RecentTask[]>(() => getRecentTasks());

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
        />
      ) : null}
    </main>
  );
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
