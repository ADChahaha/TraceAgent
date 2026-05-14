export type AppTheme = "light" | "dark";

export const THEME_STORAGE_KEY = "agent-gate.theme";
export const THEME_CHANGED_EVENT = "agent-gate-theme-change";

export function getStoredTheme(): AppTheme {
  if (typeof window === "undefined") {
    return "light";
  }
  const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
  return stored === "dark" ? "dark" : "light";
}

export function applyStoredTheme(theme: AppTheme): void {
  if (typeof document === "undefined") {
    return;
  }
  document.documentElement.dataset.theme = theme;
  if (typeof window !== "undefined") {
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
    window.dispatchEvent(new CustomEvent(THEME_CHANGED_EVENT, { detail: theme }));
  }
}
