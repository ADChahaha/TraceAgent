"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { toast } from "sonner";

import {
  loadTaskDetail as defaultLoadTaskDetail,
  submitTaskReview as defaultSubmitReview
} from "@/lib/api";
import { stringifyValue } from "@/lib/json";
import { updateRecentTask } from "@/lib/task-store";
import type {
  ReviewSubmitPayload,
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
  submitReview?: (taskId: string, payload: ReviewSubmitPayload) => Promise<TaskSummary>;
}

export function TaskDetail({
  taskId,
  initialSummary,
  loadTaskDetail = defaultLoadTaskDetail,
  submitReview = defaultSubmitReview
}: TaskDetailProps) {
  const [detail, setDetail] = React.useState<TaskDetailData | null>(
    initialSummary
      ? { summary: initialSummary, result: null, trace: null, replay: null, review: null, audit: null }
      : null
  );
  const [reviewValues, setReviewValues] = React.useState<Record<string, unknown>>({});
  const [comment, setComment] = React.useState("");
  const [isLoading, setIsLoading] = React.useState(true);
  const [isSubmitting, setIsSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const refresh = React.useCallback(async () => {
    setError(null);
    try {
      const loaded = await loadTaskDetail(taskId);
      setDetail(loaded);
      updateRecentTask(loaded.summary);
      setReviewValues((current) => {
        if (!loaded.review) {
          return current;
        }
        const next = { ...current };
        for (const field of loaded.review.fields) {
          if (!(field.field_name in next)) {
            next[field.field_name] = getInitialReviewValue(field.agent_value);
          }
        }
        return next;
      });
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

  async function handleSubmitReview() {
    if (!detail?.review) {
      return;
    }
    const fields = detail.review.fields
      .filter((field) => field.needs_review)
      .map((field) => ({
        field_name: field.field_name,
        review_value: reviewValues[field.field_name] ?? getInitialReviewValue(field.agent_value)
      }));
    const payload: ReviewSubmitPayload = {
      decision: "revise_and_approve",
      fields,
      comment,
      reviewer: "frontend"
    };

    setIsSubmitting(true);
    setError(null);
    try {
      await submitReview(taskId, payload);
      toast.success("复核已提交");
      await refresh();
    } catch (submitError) {
      const message = submitError instanceof Error ? submitError.message : "提交复核失败";
      setError(message);
      toast.error("提交复核失败", { description: message });
    } finally {
      setIsSubmitting(false);
    }
  }

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
          finalFields={detail.result?.fields ?? []}
          reviewFields={detail.review?.fields ?? []}
          reviewValues={reviewValues}
          reviewComment={comment}
          isSubmittingReview={isSubmitting}
          onReviewValueChange={(fieldName, value) =>
            setReviewValues((current) => ({
              ...current,
              [fieldName]: value
            }))
          }
          onReviewCommentChange={setComment}
          onSubmitReview={() => void handleSubmitReview()}
        />
      ) : null}
    </main>
  );
}

function StatusBadge({ status }: { status: TaskSummary["status"] }) {
  if (status === "completed") {
    return <Badge variant="success">{status}</Badge>;
  }
  if (status === "waiting_review" || status === "processing" || status === "pending") {
    return <Badge variant="warning">{status}</Badge>;
  }
  if (status === "failed" || status === "rejected") {
    return <Badge variant="destructive">{status}</Badge>;
  }
  return <Badge variant="secondary">{status}</Badge>;
}

function getInitialReviewValue(value: unknown): unknown {
  if (isTaggedEnumValue(value)) {
    return value;
  }
  return stringifyValue(value);
}

function isTaggedEnumValue(value: unknown): value is { variant: string; value: unknown } {
  return (
    value !== null &&
    typeof value === "object" &&
    !Array.isArray(value) &&
    "variant" in value &&
    typeof (value as { variant?: unknown }).variant === "string"
  );
}
