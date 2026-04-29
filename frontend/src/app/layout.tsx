import type { Metadata } from "next";

import "./globals.css";
import { Toaster } from "@/components/ui/sonner";

export const metadata: Metadata = {
  title: "Agent Gate",
  description: "文档上传、字段治理、人工复核和审计工作台"
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>
        <div className="mx-auto w-full max-w-7xl px-5 py-8 sm:px-8">{children}</div>
        <Toaster richColors closeButton />
      </body>
    </html>
  );
}
