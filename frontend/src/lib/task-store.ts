import type { RouteDecision, TaskCreated, TaskSummary } from "@/lib/types";

export interface RecentTask {
  task_id: string;
  status: TaskSummary["status"];
  stage: TaskSummary["stage"];
  route?: RouteDecision | null;
  route_reason?: string | null;
  error_message?: string | null;
  has_result?: boolean;
  has_trace?: boolean;
  needs_review?: boolean;
  created_at: string;
  updated_at?: string;
}

const RECENT_TASKS_KEY = "agent-gate.recent-tasks";
const MAX_RECENT_TASKS = 8;

export function getRecentTasks(): RecentTask[] {
  if (typeof window === "undefined") {
    return [];
  }
  try {
    const parsed = JSON.parse(window.localStorage.getItem(RECENT_TASKS_KEY) ?? "[]");
    return Array.isArray(parsed) ? (parsed as RecentTask[]) : [];
  } catch {
    return [];
  }
}

export function addRecentTask(task: TaskCreated): RecentTask[] {
  if (typeof window === "undefined") {
    return [];
  }
  const existing = getRecentTasks();
  const next = [
    toRecentTask(task, existing.find((item) => item.task_id === task.task_id)),
    ...existing.filter((item) => item.task_id !== task.task_id)
  ].slice(0, MAX_RECENT_TASKS);
  try {
    window.localStorage.setItem(RECENT_TASKS_KEY, JSON.stringify(next));
  } catch {
    return next;
  }
  return next;
}

export function updateRecentTask(task: TaskSummary): RecentTask[] {
  if (typeof window === "undefined") {
    return [];
  }
  const existing = getRecentTasks();
  const current = existing.find((item) => item.task_id === task.task_id);
  const updated = toRecentTask(task, current);
  const next = current
    ? existing.map((item) => (item.task_id === task.task_id ? updated : item))
    : [updated, ...existing].slice(0, MAX_RECENT_TASKS);
  try {
    window.localStorage.setItem(RECENT_TASKS_KEY, JSON.stringify(next));
  } catch {
    return next;
  }
  return next;
}

function toRecentTask(task: TaskCreated | TaskSummary, existing?: RecentTask): RecentTask {
  const backendCreatedAt = "created_at" in task ? task.created_at : undefined;
  const backendUpdatedAt = "updated_at" in task ? task.updated_at : undefined;
  return {
    task_id: task.task_id,
    status: task.status,
    stage: task.stage,
    route: "route" in task ? task.route : existing?.route,
    route_reason: "route_reason" in task ? task.route_reason : existing?.route_reason,
    error_message: task.error_message ?? null,
    has_result: "has_result" in task ? task.has_result : existing?.has_result,
    has_trace: "has_trace" in task ? task.has_trace : existing?.has_trace,
    needs_review: "needs_review" in task ? task.needs_review : existing?.needs_review,
    created_at: backendCreatedAt ?? existing?.created_at ?? new Date().toISOString(),
    updated_at: backendUpdatedAt ?? existing?.updated_at
  };
}
