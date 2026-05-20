"use client";

import { useRouter } from "next/navigation";

import { UploadWorkbench } from "@/components/upload-workbench";

export function HomeWorkspace() {
  const router = useRouter();
  return <UploadWorkbench onCreated={(task) => router.push(`/tasks/${task.task_id}`)} />;
}
