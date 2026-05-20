import type { TaskCreated, TaskSummary } from "@/lib/types";

export interface RecentTask {
  task_id: string;
  status: TaskSummary["status"];
  stage: TaskSummary["stage"];
  error_message?: string | null;
  has_result?: boolean;
  has_trace?: boolean;
  created_at: string;
  updated_at?: string;
}

const RECENT_TASKS_KEY = "agent-gate.recent-tasks";
const RECENT_TASKS_CHANGED_EVENT = "agent-gate-recent-tasks-change";
const MAX_RECENT_TASKS = 8;
const EMPTY_RECENT_TASKS: RecentTask[] = [];

let recentTasksSnapshotRaw: string | null = null;
let recentTasksSnapshot: RecentTask[] = EMPTY_RECENT_TASKS;

export function getRecentTasks(): RecentTask[] {
  return getRecentTasksSnapshot();
}

export function getRecentTasksSnapshot(): RecentTask[] {
  if (typeof window === "undefined") {
    return EMPTY_RECENT_TASKS;
  }
  const raw = window.localStorage.getItem(RECENT_TASKS_KEY) ?? "[]";
  if (raw === recentTasksSnapshotRaw) {
    return recentTasksSnapshot;
  }
  recentTasksSnapshotRaw = raw;
  recentTasksSnapshot = parseRecentTasks(raw);
  return recentTasksSnapshot;
}

export function getServerRecentTasksSnapshot(): RecentTask[] {
  return EMPTY_RECENT_TASKS;
}

export function subscribeRecentTasks(onStoreChange: () => void): () => void {
  if (typeof window === "undefined") {
    return () => undefined;
  }
  const handleStorage = (event: StorageEvent) => {
    if (!event.key || event.key === RECENT_TASKS_KEY) {
      onStoreChange();
    }
  };
  window.addEventListener(RECENT_TASKS_CHANGED_EVENT, onStoreChange);
  window.addEventListener("storage", handleStorage);
  return () => {
    window.removeEventListener(RECENT_TASKS_CHANGED_EVENT, onStoreChange);
    window.removeEventListener("storage", handleStorage);
  };
}

function parseRecentTasks(raw: string): RecentTask[] {
  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as RecentTask[]) : EMPTY_RECENT_TASKS;
  } catch {
    return EMPTY_RECENT_TASKS;
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
  return writeRecentTasks(next);
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
  return writeRecentTasks(next);
}

export function syncRecentTaskSummaries(tasks: TaskSummary[]): RecentTask[] {
  if (typeof window === "undefined") {
    return [];
  }
  const existing = getRecentTasks();
  const existingById = new Map(existing.map((item) => [item.task_id, item]));
  const syncedIds = new Set(tasks.map((task) => task.task_id));
  const next = [
    ...tasks.map((task) => toRecentTask(task, existingById.get(task.task_id))),
    ...existing.filter((item) => !syncedIds.has(item.task_id)),
  ].slice(0, MAX_RECENT_TASKS);
  return writeRecentTasks(next);
}

function writeRecentTasks(next: RecentTask[]): RecentTask[] {
  if (typeof window === "undefined") {
    return EMPTY_RECENT_TASKS;
  }
  const serialized = JSON.stringify(next);
  recentTasksSnapshotRaw = serialized;
  recentTasksSnapshot = next;
  try {
    window.localStorage.setItem(RECENT_TASKS_KEY, serialized);
  } finally {
    window.dispatchEvent(new Event(RECENT_TASKS_CHANGED_EVENT));
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
    error_message: task.error_message ?? null,
    has_result: "has_result" in task ? task.has_result : existing?.has_result,
    has_trace: "has_trace" in task ? task.has_trace : existing?.has_trace,
    created_at: backendCreatedAt ?? existing?.created_at ?? new Date().toISOString(),
    updated_at: backendUpdatedAt ?? existing?.updated_at
  };
}
