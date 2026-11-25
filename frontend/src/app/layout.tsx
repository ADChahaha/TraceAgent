import type { Metadata } from "next";

import "./globals.css";
import { ThemeBootstrap } from "@/components/theme-bootstrap";
import { Toaster } from "@/components/ui/sonner";

export const metadata: Metadata = {
  title: "TraceAgent",
  description: "Document QA workspace with traceable evidence"
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <ThemeBootstrap />
        <div className="mx-auto w-full max-w-7xl px-5 py-8 sm:px-8">{children}</div>
        <Toaster richColors closeButton />
      </body>
    </html>
  );
}
