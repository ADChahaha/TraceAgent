"use client";

import { useEffect, useState, useSyncExternalStore, type CSSProperties, type ReactNode } from "react";
import Link from "next/link";
import { Moon, Sun, Menu, Plus, BookOpen, X } from "lucide-react";
import { applyStoredTheme, getServerThemeSnapshot, getThemeSnapshot, subscribeTheme } from "@/lib/theme";
import { recentSessions, serverSessions, subscribeSessions } from "@/lib/session-store";
import { LeftSidebarResizeHandle, useLeftSidebarResize } from "@/components/sidebar-resize";
import styles from "./workspace.module.css";

function subscribeWidth(listener: () => void) {
  window.addEventListener("resize", listener);
  return () => window.removeEventListener("resize", listener);
}
const compactWidth = () => window.innerWidth <= 800;
const serverWidth = () => false;

export function WorkspaceShell({ sessionId, status, children, review, reviewRequest = 0 }: {
  sessionId?: string; status?: string; children: ReactNode; review?: ReactNode; reviewRequest?: number;
}) {
  const [open, setOpen] = useState(false);
  const [mobileReview, setMobileReview] = useState(false);
  const compact = useSyncExternalStore(subscribeWidth, compactWidth, serverWidth);
  const sessions = useSyncExternalStore(subscribeSessions, recentSessions, serverSessions);
  const theme = useSyncExternalStore(subscribeTheme, getThemeSnapshot, getServerThemeSnapshot);
  const left = useLeftSidebarResize();
  useEffect(() => { applyStoredTheme(theme); }, [theme]);
  useEffect(() => {
    if (reviewRequest) {
      // 点击引用后切换到原文，避免窄屏隐藏证据。
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
  return <section className={styles.root} aria-label={sessionId ? "QA document workspace" : "Home task workbench"}>
    <header className={styles.topbar}>
      <div className={styles.brand}>
        <button aria-label={open ? "Close sidebar" : "Open sidebar"} aria-expanded={open} onClick={() => setOpen(!open)}><Menu size={21} /></button>
        <Link href="/"><BookOpen size={23} /><span>Agent Gate</span></Link>
      </div>
      <div className={styles.controls}>
        {status && <span role="status" className={styles.status}>{status === "idle" ? "Ready" : status === "live" ? "Answering" : status}</span>}
        {compact && review && <button onClick={() => setMobileReview(!mobileReview)}>{mobileReview ? "Chat" : "Documents"}</button>}
        <button aria-label="Toggle theme" onClick={() => applyStoredTheme(theme === "dark" ? "light" : "dark")}>
          {theme === "dark" ? <Moon size={18} /> : <Sun size={18} />}<span>{theme === "dark" ? "Dark" : "Light"}</span>
        </button>
        <Link href="/" className={styles.newLink}><Plus size={17} /><span>New workspace</span></Link>
      </div>
    </header>
    {open && <>
      <button className={styles.backdrop} aria-label="Dismiss sidebar" onClick={() => setOpen(false)} />
      <aside className={styles.sidebar} aria-label="Tasks sidebar">
        <div className={styles.drawerHeading}><h2>Recent workspaces</h2><button aria-label="Close recent workspaces" onClick={() => setOpen(false)}><X size={18} /></button></div>
        <nav aria-label="Recent sessions">
          {sessions.length === 0 && <p>No workspaces yet.</p>}
          {sessions.map((session) => <Link key={session.id} href={`/tasks/${encodeURIComponent(session.id)}`} onClick={() => setOpen(false)} aria-current={session.id === sessionId ? "page" : undefined}>
            <BookOpen size={18} /><span>{session.id}<small>{session.status}</small></span>
          </Link>)}
        </nav>
      </aside>
    </>}
    <div className={styles.stage} aria-label="QA stage" data-has-review={Boolean(review)} data-mobile-review={compact && mobileReview ? "true" : "false"}
      style={{ "--source-width": `${left.leftPanelWidth + 96}px` } as CSSProperties}>
      {review && (!compact || mobileReview) && <>
        <aside className={styles.review} aria-label="Document review">{review}</aside>
        {!compact && <LeftSidebarResizeHandle width={left.leftPanelWidth} onPointerDown={left.startLeftPanelResize} onKeyDown={left.resizeLeftPanelByKeyboard} />}
      </>}
      <div className={styles.content}>{children}</div>
    </div>
  </section>;
}
