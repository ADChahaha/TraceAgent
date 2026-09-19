import { Check, Loader2 } from "lucide-react";
import type { FileUpload } from "@/lib/use-file-uploads";

export function UploadStatus({ item, onRetry, disabled = false }: { item: FileUpload; onRetry: () => void; disabled?: boolean }) {
  const name = item.file.name;
  if (item.status === "processing" || item.status === "removing") return <span role="status" aria-label={`${item.status === "removing" ? "Removing" : "Processing"} ${name}`} title={item.status === "removing" ? "Removing" : "Processing"} className="shrink-0 text-blue-500"><Loader2 size={17} className="animate-spin" aria-hidden="true" /></span>;
  if (item.status === "queued") return <span role="status" aria-label={`Queued ${name}`} className="text-xs text-muted-foreground">Queued</span>;
  if (item.status === "failed") return <button type="button" disabled={disabled} aria-label={`Retry ${name}`} onClick={onRetry} className="text-xs text-destructive">Retry</button>;
  return <span role="status" aria-label={`Ready ${name}`} title="Ready" className="shrink-0 text-blue-500"><Check size={16} aria-hidden="true" /></span>;
}
