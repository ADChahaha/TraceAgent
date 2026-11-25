"use client";

import * as React from "react";

export const LEFT_PANEL_MIN_WIDTH = 220;
export const LEFT_PANEL_MAX_WIDTH = 1200;
const RIGHT_PANE_MIN_WIDTH = 320;
const LEFT_PANEL_KEY_STEP = 24;
export const DEFAULT_LEFT_PANEL_WIDTH = 560;
const RIGHT_PANEL_MIN_WIDTH = 480;
const RIGHT_PANEL_MAX_WIDTH = 960;
const RIGHT_PANEL_KEY_STEP = 16;
export const DEFAULT_RIGHT_PANEL_WIDTH = 560;

export function useLeftSidebarResize() {
  // null means default ~50% split via CSS until the user drags or adjusts with keyboard.
  const [leftPanelWidth, setLeftPanelWidth] = React.useState<number | null>(null);

  const startLeftPanelResize = React.useCallback(
    (event: React.PointerEvent<HTMLButtonElement>) => {
      event.preventDefault();
      const handle = event.currentTarget;
      const startX = readClientX(event);
      if (startX === null) {
        return;
      }
      const previousPane = handle.previousElementSibling;
      const measuredWidth = previousPane ? Math.round(previousPane.getBoundingClientRect().width) : 0;
      const startWidth = leftPanelWidth ?? (measuredWidth >= LEFT_PANEL_MIN_WIDTH ? measuredWidth : resolveDefaultSplitWidth());
      const pointerId = event.pointerId;

      const updateWidth = (clientX: number) => {
        setLeftPanelWidth(clampLeftPanelWidth(startWidth + clientX - startX));
      };
      const stopResize = () => {
        window.removeEventListener("pointermove", handlePointerMove);
        window.removeEventListener("pointerup", handlePointerEnd);
        window.removeEventListener("pointercancel", handlePointerEnd);
        document.body.classList.remove("is-resizing-replay-panel");
        try {
          handle.releasePointerCapture(pointerId);
        } catch {
          // Older browsers and JSDOM may not support pointer capture.
        }
      };
      const handlePointerMove = (moveEvent: PointerEvent) => {
        moveEvent.preventDefault();
        const clientX = readClientX(moveEvent);
        if (clientX !== null) {
          updateWidth(clientX);
        }
      };
      const handlePointerEnd = (moveEvent: PointerEvent) => {
        moveEvent.preventDefault();
        const clientX = readClientX(moveEvent);
        if (clientX !== null) {
          updateWidth(clientX);
        }
        stopResize();
      };

      document.body.classList.add("is-resizing-replay-panel");
      try {
        handle.setPointerCapture(pointerId);
      } catch {
        // Older browsers and JSDOM may not support pointer capture.
      }
      window.addEventListener("pointermove", handlePointerMove);
      window.addEventListener("pointerup", handlePointerEnd);
      window.addEventListener("pointercancel", handlePointerEnd);
    },
    [leftPanelWidth]
  );

  const resizeLeftPanelByKeyboard = React.useCallback((event: React.KeyboardEvent<HTMLButtonElement>) => {
    const maxWidth = resolveDynamicMaxWidth();
    if (event.key === "Home") {
      event.preventDefault();
      setLeftPanelWidth(LEFT_PANEL_MIN_WIDTH);
      return;
    }
    if (event.key === "End") {
      event.preventDefault();
      setLeftPanelWidth(maxWidth);
      return;
    }
    const delta = event.key === "ArrowLeft" ? -LEFT_PANEL_KEY_STEP : event.key === "ArrowRight" ? LEFT_PANEL_KEY_STEP : 0;
    if (delta === 0) {
      return;
    }
    event.preventDefault();
    setLeftPanelWidth((current) => clampLeftPanelWidth((current ?? resolveDefaultSplitWidth()) + delta));
  }, []);

  return {
    leftPanelWidth,
    resizeLeftPanelByKeyboard,
    startLeftPanelResize,
  };
}

export function useRightSidebarResize() {
  const [rightPanelWidth, setRightPanelWidth] = React.useState(DEFAULT_RIGHT_PANEL_WIDTH);

  const startRightPanelResize = React.useCallback(
    (event: React.PointerEvent<HTMLButtonElement>) => {
      event.preventDefault();
      const handle = event.currentTarget;
      const startX = readClientX(event);
      if (startX === null) {
        return;
      }
      const startWidth = rightPanelWidth;
      const pointerId = event.pointerId;

      const updateWidth = (clientX: number) => {
        setRightPanelWidth(clampRightPanelWidth(startWidth + clientX - startX));
      };
      const stopResize = () => {
        window.removeEventListener("pointermove", handlePointerMove);
        window.removeEventListener("pointerup", handlePointerEnd);
        window.removeEventListener("pointercancel", handlePointerEnd);
        document.body.classList.remove("is-resizing-replay-panel");
        try {
          handle.releasePointerCapture(pointerId);
        } catch {
          // Older browsers and JSDOM may not support pointer capture.
        }
      };
      const handlePointerMove = (moveEvent: PointerEvent) => {
        moveEvent.preventDefault();
        const clientX = readClientX(moveEvent);
        if (clientX !== null) {
          updateWidth(clientX);
        }
      };
      const handlePointerEnd = (moveEvent: PointerEvent) => {
        moveEvent.preventDefault();
        const clientX = readClientX(moveEvent);
        if (clientX !== null) {
          updateWidth(clientX);
        }
        stopResize();
      };

      document.body.classList.add("is-resizing-replay-panel");
      try {
        handle.setPointerCapture(pointerId);
      } catch {
        // Older browsers and JSDOM may not support pointer capture.
      }
      window.addEventListener("pointermove", handlePointerMove);
      window.addEventListener("pointerup", handlePointerEnd);
      window.addEventListener("pointercancel", handlePointerEnd);
    },
    [rightPanelWidth]
  );

  const resizeRightPanelByKeyboard = React.useCallback((event: React.KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === "Home") {
      event.preventDefault();
      setRightPanelWidth(RIGHT_PANEL_MIN_WIDTH);
      return;
    }
    if (event.key === "End") {
      event.preventDefault();
      setRightPanelWidth(RIGHT_PANEL_MAX_WIDTH);
      return;
    }
    const delta = event.key === "ArrowRight" ? RIGHT_PANEL_KEY_STEP : event.key === "ArrowLeft" ? -RIGHT_PANEL_KEY_STEP : 0;
    if (delta === 0) {
      return;
    }
    event.preventDefault();
    setRightPanelWidth((current) => clampRightPanelWidth(current + delta));
  }, []);

  return {
    rightPanelWidth,
    resizeRightPanelByKeyboard,
    startRightPanelResize,
  };
}

export function LeftSidebarResizeHandle({
  width,
  onPointerDown,
  onKeyDown,
}: {
  width: number | null;
  onPointerDown: (event: React.PointerEvent<HTMLButtonElement>) => void;
  onKeyDown: (event: React.KeyboardEvent<HTMLButtonElement>) => void;
}) {
  return (
    <button
      type="button"
      role="separator"
      aria-label="Resize left sidebar"
      aria-orientation="vertical"
      aria-valuemin={LEFT_PANEL_MIN_WIDTH}
      aria-valuemax={LEFT_PANEL_MAX_WIDTH}
      aria-valuenow={width ?? DEFAULT_LEFT_PANEL_WIDTH}
      className="replay-panel-resize-handle"
      title="Drag to resize panels"
      onPointerDown={onPointerDown}
      onKeyDown={onKeyDown}
    >
      <span className="replay-panel-resize-grip" aria-hidden="true" />
    </button>
  );
}

export function RightSidebarResizeHandle({
  width,
  onPointerDown,
  onKeyDown,
}: {
  width: number;
  onPointerDown: (event: React.PointerEvent<HTMLButtonElement>) => void;
  onKeyDown: (event: React.KeyboardEvent<HTMLButtonElement>) => void;
}) {
  return (
    <button
      type="button"
      role="separator"
      aria-label="Resize right review"
      aria-orientation="vertical"
      aria-valuemin={RIGHT_PANEL_MIN_WIDTH}
      aria-valuemax={RIGHT_PANEL_MAX_WIDTH}
      aria-valuenow={width}
      className="replay-panel-resize-handle"
      title="Resize right review"
      onPointerDown={onPointerDown}
      onKeyDown={onKeyDown}
    >
      <span className="replay-panel-resize-grip" aria-hidden="true" />
    </button>
  );
}

function resolveDynamicMaxWidth(): number {
  if (typeof window === "undefined" || !Number.isFinite(window.innerWidth) || window.innerWidth <= 0) {
    return LEFT_PANEL_MAX_WIDTH;
  }
  return Math.min(LEFT_PANEL_MAX_WIDTH, Math.max(LEFT_PANEL_MIN_WIDTH, window.innerWidth - RIGHT_PANE_MIN_WIDTH));
}

function resolveDefaultSplitWidth(): number {
  if (typeof window === "undefined" || !Number.isFinite(window.innerWidth) || window.innerWidth <= 0) {
    return DEFAULT_LEFT_PANEL_WIDTH;
  }
  return clampLeftPanelWidth(Math.round(window.innerWidth * 0.5));
}

function clampLeftPanelWidth(width: number): number {
  return Math.min(resolveDynamicMaxWidth(), Math.max(LEFT_PANEL_MIN_WIDTH, Math.round(width)));
}

function clampRightPanelWidth(width: number): number {
  return Math.min(RIGHT_PANEL_MAX_WIDTH, Math.max(RIGHT_PANEL_MIN_WIDTH, Math.round(width)));
}

function readClientX(event: Pick<MouseEvent, "clientX">): number | null {
  return Number.isFinite(event.clientX) ? event.clientX : null;
}
