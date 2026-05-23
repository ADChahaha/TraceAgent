"use client";

import * as React from "react";

const LEFT_PANEL_MIN_WIDTH = 176;
const LEFT_PANEL_MAX_WIDTH = 360;
const LEFT_PANEL_KEY_STEP = 16;
export const DEFAULT_LEFT_PANEL_WIDTH = 224;
const RIGHT_PANEL_MIN_WIDTH = 480;
const RIGHT_PANEL_MAX_WIDTH = 960;
const RIGHT_PANEL_KEY_STEP = 16;
export const DEFAULT_RIGHT_PANEL_WIDTH = 560;

export function useLeftSidebarResize() {
  const [leftPanelWidth, setLeftPanelWidth] = React.useState(DEFAULT_LEFT_PANEL_WIDTH);

  const startLeftPanelResize = React.useCallback(
    (event: React.PointerEvent<HTMLButtonElement>) => {
      event.preventDefault();
      const handle = event.currentTarget;
      const startX = readClientX(event);
      if (startX === null) {
        return;
      }
      const startWidth = leftPanelWidth;
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
    if (event.key === "Home") {
      event.preventDefault();
      setLeftPanelWidth(LEFT_PANEL_MIN_WIDTH);
      return;
    }
    if (event.key === "End") {
      event.preventDefault();
      setLeftPanelWidth(LEFT_PANEL_MAX_WIDTH);
      return;
    }
    const delta = event.key === "ArrowLeft" ? -LEFT_PANEL_KEY_STEP : event.key === "ArrowRight" ? LEFT_PANEL_KEY_STEP : 0;
    if (delta === 0) {
      return;
    }
    event.preventDefault();
    setLeftPanelWidth((current) => clampLeftPanelWidth(current + delta));
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
        setRightPanelWidth(clampRightPanelWidth(startWidth + startX - clientX));
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
    const delta = event.key === "ArrowLeft" ? RIGHT_PANEL_KEY_STEP : event.key === "ArrowRight" ? -RIGHT_PANEL_KEY_STEP : 0;
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
  width: number;
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
      aria-valuenow={width}
      className="replay-panel-resize-handle"
      title="Resize left sidebar"
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

function clampLeftPanelWidth(width: number): number {
  return Math.min(LEFT_PANEL_MAX_WIDTH, Math.max(LEFT_PANEL_MIN_WIDTH, width));
}

function clampRightPanelWidth(width: number): number {
  return Math.min(RIGHT_PANEL_MAX_WIDTH, Math.max(RIGHT_PANEL_MIN_WIDTH, width));
}

function readClientX(event: Pick<MouseEvent, "clientX">): number | null {
  return Number.isFinite(event.clientX) ? event.clientX : null;
}
