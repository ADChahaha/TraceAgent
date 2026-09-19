"use client";

import { useRouter } from "next/navigation";

import { UploadWorkbench } from "@/components/upload-workbench";

export function HomeWorkspace() {
  const router = useRouter();
  return <UploadWorkbench onCreated={(sessionId) => router.push(`/tasks/${encodeURIComponent(sessionId)}`)} />;
}
