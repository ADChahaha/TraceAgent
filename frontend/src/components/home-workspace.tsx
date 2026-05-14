"use client";

import * as React from "react";
import { getCapabilities } from "@/lib/api";
import type { Capabilities } from "@/lib/types";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import { UploadWorkbench } from "@/components/upload-workbench";

export function HomeWorkspace() {
  const [capabilities, setCapabilities] = React.useState<Capabilities | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    let mounted = true;
    getCapabilities()
      .then((loaded) => {
        if (mounted) {
          setCapabilities(loaded);
        }
      })
      .catch((loadError) => {
        if (mounted) {
          setError(loadError instanceof Error ? loadError.message : "无法读取 backend 能力");
        }
      });
    return () => {
      mounted = false;
    };
  }, []);

  if (error) {
    return (
      <Alert variant="destructive">
        <AlertTitle>无法连接 backend</AlertTitle>
        <AlertDescription>{error}</AlertDescription>
      </Alert>
    );
  }

  if (!capabilities) {
    return (
      <main className="space-y-5">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-[28rem] w-full" />
      </main>
    );
  }

  return (
    <main className="space-y-4">
      <UploadWorkbench capabilities={capabilities} />
    </main>
  );
}
