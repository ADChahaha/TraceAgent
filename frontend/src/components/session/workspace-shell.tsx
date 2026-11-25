"use client";

import { useEffect, useState, useSyncExternalStore, type CSSProperties, type ReactNode } from "react";
import Link from "next/link";
import { BookOpen, Menu, Moon, Plus, Sun, X } from "lucide-react";
import { applyStoredTheme, getServerThemeSnapshot, getThemeSnapshot, subscribeTheme } from "@/lib/theme";
import { WorkspaceList } from "./workspace-list";
import { LeftSidebarResizeHandle, useLeftSidebarResize } from "@/components/sidebar-resize";
import styles from "./workspace.module.css";

function subscribeWidth(listener: () => void) {
  window.addEventListener("resize", listener);
  return () => window.removeEventListener("resize", listener);
}
const compactWidth = () => window.innerWidth <= 800;
const serverWidth = () => false;

export function WorkspaceShell({ sessionId, sessionTitle, status, children, review, reviewRequest = 0 }: {
  sessionId?: string;
  sessionTitle?: string;
  status?: string;
  children: ReactNode;
  review?: ReactNode;
  reviewRequest?: number;
}) {
  const [open, setOpen] = useState(false);
  const [mobileReview, setMobileReview] = useState(false);
  const compact = useSyncExternalStore(subscribeWidth, compactWidth, serverWidth);
  const theme = useSyncExternalStore(subscribeTheme, getThemeSnapshot, getServerThemeSnapshot);
  const left = useLeftSidebarResize();
  useEffect(() => { applyStoredTheme(theme); }, [theme]);
  useEffect(() => {
    if (reviewRequest) {
      // Switch to document view on narrow viewports without touching desktop split width.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setMobileReview(true);
    }
  }, [reviewRequest]);
  useEffect(() => {
    if (!open) return;
    const close = (event: KeyboardEvent) => { if (event.key === "Escape") setOpen(false); };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [open]);

  const stageStyle = left.leftPanelWidth !== null
    ? ({ "--source-width": `${left.leftPanelWidth}px` } as CSSProperties)
    : undefined;

  return <section className={styles.root} aria-label={sessionId ? "QA document workspace" : "Home task workbench"}>
    <header className={styles.topbar}>
      <div className={styles.brand}>
        <button type="button" className={styles.iconBtn} aria-label={open ? "Close sidebar" : "Open sidebar"} aria-expanded={open} title="Recent workspaces" onClick={() => setOpen(!open)}>
          <Menu size={16} strokeWidth={1.75} />
        </button>
        <Link href="/" className={styles.iconBtn} aria-label="New workspace" title="New workspace">
          <Plus size={16} strokeWidth={1.85} />
        </Link>
        <Link href="/" className={styles.brandLink}>
          <BookOpen size={15} strokeWidth={1.9} />
          <span>TraceAgent</span>
        </Link>
        {sessionTitle && <>
          <span className={styles.brandDivider} aria-hidden="true">/</span>
          <span className={styles.sessionTitle} title={sessionTitle}>{sessionTitle}</span>
        </>}
      </div>
      <div className={styles.controls}>
        {status && <span role="status" className={styles.status}>{status === "idle" ? "Ready" : status === "live" ? "Answering" : status}</span>}
        {compact && review && <button type="button" className={styles.mobileSwitch} onClick={() => setMobileReview(!mobileReview)}>{mobileReview ? "Chat" : "Documents"}</button>}
        <button type="button" className={styles.iconBtn} aria-label="Toggle theme" title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"} onClick={() => applyStoredTheme(theme === "dark" ? "light" : "dark")}>
          {theme === "dark" ? <Moon size={15} strokeWidth={1.75} /> : <Sun size={15} strokeWidth={1.75} />}
        </button>
      </div>
    </header>
    {open && <>
      <button type="button" className={styles.backdrop} aria-label="Dismiss sidebar" onClick={() => setOpen(false)} />
      <aside className={styles.sidebar} aria-label="Tasks sidebar">
        <div className={styles.drawerHeading}>
          <h2>Recent workspaces</h2>
          <button type="button" className={styles.iconBtn} aria-label="Close recent workspaces" onClick={() => setOpen(false)}><X size={15} /></button>
        </div>
        <WorkspaceList sessionId={sessionId} onSelect={() => setOpen(false)} />
      </aside>
    </>}
    <div className={styles.stage} aria-label="QA stage" data-has-review={Boolean(review)} data-mobile-review={compact && mobileReview ? "true" : "false"} style={stageStyle}>
      {review && (!compact || mobileReview) && <>
        <aside className={styles.review} aria-label="Document review">{review}</aside>
        {!compact && <LeftSidebarResizeHandle width={left.leftPanelWidth} onPointerDown={left.startLeftPanelResize} onKeyDown={left.resizeLeftPanelByKeyboard} />}
      </>}
      <div className={styles.content}>{children}</div>
    </div>
  </section>;
}
