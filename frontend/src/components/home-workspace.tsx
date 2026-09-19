"use client";

import { saveWorkspaceDraft } from "@/lib/session-store";
import { useRouter } from "next/navigation";

import { UploadWorkbench } from "@/components/upload-workbench";

export function HomeWorkspace() {
  const router = useRouter();
  return <UploadWorkbench onFilesReady={(sessionId, draft) => {
    saveWorkspaceDraft(sessionId, draft);
    router.push(`/tasks/${encodeURIComponent(sessionId)}`);
  }} onCreated={(sessionId) => router.push(`/tasks/${encodeURIComponent(sessionId)}`)} />;
}
