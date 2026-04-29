import type { TaskCreated } from "@/lib/types";

export interface RecentTask {
  task_id: string;
  status: TaskCreated["status"];
  stage: TaskCreated["stage"];
  created_at: string;
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
  const next = [
    {
      task_id: task.task_id,
      status: task.status,
      stage: task.stage,
      created_at: new Date().toISOString()
    },
    ...getRecentTasks().filter((item) => item.task_id !== task.task_id)
  ].slice(0, MAX_RECENT_TASKS);
  try {
    window.localStorage.setItem(RECENT_TASKS_KEY, JSON.stringify(next));
  } catch {
    return next;
  }
  return next;
}

export function updateRecentTask(task: TaskCreated): RecentTask[] {
  if (typeof window === "undefined") {
    return [];
  }
  const existing = getRecentTasks();
  const current = existing.find((item) => item.task_id === task.task_id);
  const next = [
    {
      task_id: task.task_id,
      status: task.status,
      stage: task.stage,
      created_at: current?.created_at ?? new Date().toISOString()
    },
    ...existing.filter((item) => item.task_id !== task.task_id)
  ].slice(0, MAX_RECENT_TASKS);
  try {
    window.localStorage.setItem(RECENT_TASKS_KEY, JSON.stringify(next));
  } catch {
    return next;
  }
  return next;
}
