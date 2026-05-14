"use client";

import * as React from "react";
import { ChevronRight, Expand, Gauge, Loader2, MousePointerClick, PanelLeftClose, PanelLeftOpen, Pause, Play, Search, SquareTerminal } from "lucide-react";

import { stringifyValue } from "@/lib/json";
import type { EnumVariantDefinition, ReplayAction, ReplayFieldState, ReplayOutlineNode, TaskReplay, TaskResultField } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import type { ReviewField } from "@/lib/types";

type ReplayMode = "auto" | "paused";

type ReplayField = {
  sourceName: string;
  fieldName: string;
  fieldType?: string | null;
  variants: EnumVariantDefinition[];
  status: string;
  value: unknown;
  evidenceIds: string[];
  route?: string | null;
  routeReason?: string | null;
  needsReview: boolean;
  reviewField?: ReviewField;
};

type HighlightState = {
  currentIds: string[];
  tableReferenceIds: string[];
  tableRowIds: string[];
  readIds: string[];
  preserveReadOrder: boolean;
};

type VirtualFileKind = "root" | "folder" | "file";

type VirtualFileNode = {
  path: string;
  label: string;
  displayLabel: string;
  kind: VirtualFileKind;
  children: VirtualFileNode[];
};

type VirtualFileTree = {
  tree: VirtualFileNode[];
  byPath: Map<string, VirtualFileNode>;
  parentByPath: Map<string, string>;
  allPaths: string[];
};

type VirtualHtmlAnchors = {
  byPath: Map<string, string>;
  byVirtualId: Map<string, string>;
  bySelector: Map<string, string>;
};

type VirtualEvidenceText = {
  path: string;
  selector: string;
  text: string;
};

type InlineEvidenceAnchor = VirtualEvidenceText & {
  id: string;
  matched: boolean;
};

type DocumentOutlineItem = {
  id: string;
  label: string;
  level: number;
};

type DocumentOutlineNode = DocumentOutlineItem & {
  children: DocumentOutlineNode[];
};

type DocumentOutline = {
  items: DocumentOutlineItem[];
  tree: DocumentOutlineNode[];
  byElementId: Map<string, string>;
  parentById: Map<string, string>;
  labelByElementId: Map<string, string>;
};

type ReplayCursor = {
  visible: boolean;
  x: number;
  y: number;
  clickTick: number;
};

type TextLineBox = {
  left: number;
  right: number;
  top: number;
  bottom: number;
};

type ReadingLine = TextLineBox & {
  spanIndexes: number[];
};

type EvidenceReadMode = "line" | "block";
type SidebarResizeSide = "left" | "right";

const TEXT_READ_DELAY_MS = 900;
const OUTLINE_STEP_MS = 520;
const DOCUMENT_READ_DELAY_MS = 520;
const DOCUMENT_LINE_SCAN_MS = 340;
const DEFAULT_LEFT_PANEL_WIDTH = 224;
const DEFAULT_RIGHT_PANEL_WIDTH = 384;
const LEFT_PANEL_MIN_WIDTH = 176;
const LEFT_PANEL_MAX_WIDTH = 360;
const RIGHT_PANEL_MIN_WIDTH = 300;
const RIGHT_PANEL_MAX_WIDTH = 560;
const PANEL_RESIZE_KEY_STEP = 16;

export function ReplayReview({
  replay,
  finalFields,
  reviewFields = [],
  reviewValues = {},
  reviewComment = "",
  isSubmittingReview = false,
  onReviewValueChange,
  onReviewCommentChange,
  onSubmitReview,
}: {
  replay: TaskReplay | null;
  finalFields: TaskResultField[];
  reviewFields?: ReviewField[];
  reviewValues?: Record<string, unknown>;
  reviewComment?: string;
  isSubmittingReview?: boolean;
  onReviewValueChange?: (fieldName: string, value: unknown) => void;
  onReviewCommentChange?: (value: string) => void;
  onSubmitReview?: () => void;
}) {
  const actions = React.useMemo(() => replay?.actions ?? [], [replay?.actions]);
  const displayHtml = replay?.display_html ?? "";
  const [index, setIndex] = React.useState(0);
  const [mode, setMode] = React.useState<ReplayMode>("paused");
  const [speed, setSpeed] = React.useState(0.75);
  const [iframeHtml, setIframeHtml] = React.useState("");
  const [manualOutlineId, setManualOutlineId] = React.useState("");
  const [manualVirtualPath, setManualVirtualPath] = React.useState("");
  const [manualOutlineTick, setManualOutlineTick] = React.useState(0);
  const [singleReplayTick, setSingleReplayTick] = React.useState(0);
  const [hoveredAgentActionIndex, setHoveredAgentActionIndex] = React.useState<number | null>(null);
  const [isLeftPanelOpen, setIsLeftPanelOpen] = React.useState(true);
  const [leftPanelWidth, setLeftPanelWidth] = React.useState(DEFAULT_LEFT_PANEL_WIDTH);
  const [rightPanelWidth, setRightPanelWidth] = React.useState(DEFAULT_RIGHT_PANEL_WIDTH);
  const [animatedPathIndex, setAnimatedPathIndex] = React.useState(-1);
  const [isUserInspecting, setIsUserInspecting] = React.useState(false);
  const [iframeInteractionTick, setIframeInteractionTick] = React.useState(0);
  const [replayCursor, setReplayCursor] = React.useState<ReplayCursor>({
    visible: true,
    x: 48,
    y: 120,
    clickTick: 0,
  });
  const [expandedOutlineIds, setExpandedOutlineIds] = React.useState<Set<string>>(() => new Set());
  const [expandedVirtualPaths, setExpandedVirtualPaths] = React.useState<Set<string> | null>(null);
  const reviewRef = React.useRef<HTMLElement | null>(null);
  const iframeRef = React.useRef<HTMLIFrameElement | null>(null);
  const outlineScrollRef = React.useRef<HTMLDivElement | null>(null);
  const outlineRefs = React.useRef(new Map<string, HTMLButtonElement>());
  const virtualTreeScrollRef = React.useRef<HTMLDivElement | null>(null);
  const virtualFileRefs = React.useRef(new Map<string, HTMLButtonElement>());
  const agentStreamRef = React.useRef<HTMLDivElement | null>(null);
  const userInspectingRef = React.useRef(false);
  const lastAutoNavigationKeyRef = React.useRef("");

  const bindEvidenceInlineAnchors = React.useMemo(
    () => getBindEvidenceInlineAnchors(actions),
    [actions],
  );
  const replayHtml = React.useMemo(
    () => (displayHtml ? buildReplayHtml(displayHtml, bindEvidenceInlineAnchors) : ""),
    [bindEvidenceInlineAnchors, displayHtml],
  );
  const stageStyle = React.useMemo(
    () => ({
      "--replay-left-panel-width": `${leftPanelWidth}px`,
      "--replay-right-panel-width": `${rightPanelWidth}px`,
    }) as React.CSSProperties,
    [leftPanelWidth, rightPanelWidth],
  );

  React.useEffect(() => {
    const timeout = window.setTimeout(() => {
      setIndex(0);
      setMode("paused");
      userInspectingRef.current = false;
      setIsUserInspecting(false);
      lastAutoNavigationKeyRef.current = "";
      setManualOutlineId("");
      setManualVirtualPath("");
      setIframeHtml(replayHtml);
    }, 0);
    return () => window.clearTimeout(timeout);
  }, [replay?.task_id, replayHtml]);

  const currentAction = actions[index] ?? null;
  const currentActionType = currentAction ? getActionType(currentAction) : "";
  const currentSetFieldName =
    currentAction && (currentActionType === "set_field" || currentActionType === "write_field")
      ? getSetFieldPayload(currentAction).name
      : "";
  const agentStreamActions = React.useMemo(
    () =>
      actions
        .map((action, actionIndex) => ({ action, actionIndex }))
        .filter(({ action, actionIndex }) => actionIndex <= index && shouldDisplayAgentAction(action)),
    [actions, index],
  );
  const visibleActionCount = React.useMemo(
    () => actions.filter(shouldDisplayAgentAction).length,
    [actions],
  );
  const documentOutline = React.useMemo<DocumentOutline>(
    () => buildDocumentOutline(displayHtml, replay?.outline_tree ?? []),
    [displayHtml, replay?.outline_tree],
  );
  const virtualFileTree = React.useMemo(
    () => buildVirtualFileTree(actions),
    [actions],
  );
  const virtualTreeKey = React.useMemo(
    () => virtualFileTree.allPaths.join("\n"),
    [virtualFileTree],
  );
  const displayedExpandedVirtualPaths = React.useMemo(
    () => expandedVirtualPaths ?? new Set(virtualTreeKey.split("\n").filter(Boolean)),
    [expandedVirtualPaths, virtualTreeKey],
  );
  const usesVirtualFileTree = virtualFileTree.allPaths.length > 1;
  const virtualHtmlAnchors = React.useMemo(
    () => buildVirtualHtmlAnchors(replayHtml || displayHtml, virtualFileTree, actions, bindEvidenceInlineAnchors),
    [actions, bindEvidenceInlineAnchors, displayHtml, replayHtml, virtualFileTree],
  );
  React.useEffect(() => {
    const timeout = window.setTimeout(() => {
      setExpandedVirtualPaths(null);
    }, 0);
    return () => window.clearTimeout(timeout);
  }, [virtualTreeKey]);
  const replayFields = React.useMemo(
    () => reduceReplayFields(actions.slice(0, index + 1), finalFields, reviewFields),
    [actions, finalFields, index, reviewFields],
  );
  const currentSetField = React.useMemo(
    () => replayFields.find((field) => field.sourceName === currentSetFieldName) ?? null,
    [currentSetFieldName, replayFields],
  );
  const fallbackReviewField = React.useMemo(() => {
    if (currentSetField || (actions.length > 0 && index < actions.length - 1)) {
      return null;
    }
    return replayFields.find((field) => field.needsReview) ?? null;
  }, [actions.length, currentSetField, index, replayFields]);
  const visibleFieldWrite = currentSetField ?? fallbackReviewField;
  const rawHighlights = React.useMemo(
    () => getHighlightState(actions.slice(0, index + 1), currentAction),
    [actions, currentAction, index],
  );
  const highlights = React.useMemo(
    () => resolveVirtualHighlightState(rawHighlights, virtualHtmlAnchors),
    [rawHighlights, virtualHtmlAnchors],
  );
  const highlightAnchorIds = React.useMemo(() => getHighlightAnchorIds(highlights), [highlights]);
  const actionOutlineId = React.useMemo(
    () => getActiveOutlineId(documentOutline, highlightAnchorIds),
    [documentOutline, highlightAnchorIds],
  );
  const activeOutlineId = !usesVirtualFileTree && isUserInspecting && manualOutlineId ? manualOutlineId : actionOutlineId;
  const actionVirtualPath = React.useMemo(
    () => getActiveVirtualPath(currentAction, virtualFileTree, rawHighlights),
    [currentAction, rawHighlights, virtualFileTree],
  );
  const activeVirtualPath =
    usesVirtualFileTree && isUserInspecting && manualVirtualPath
      ? manualVirtualPath
      : actionVirtualPath;
  const activeVirtualPathIds = React.useMemo(
    () => new Set(activeVirtualPath ? getVirtualPathIds(virtualFileTree, activeVirtualPath) : []),
    [activeVirtualPath, virtualFileTree],
  );
  const activeVirtualPathList = React.useMemo(
    () => (activeVirtualPath ? getVirtualPathIds(virtualFileTree, activeVirtualPath) : []),
    [activeVirtualPath, virtualFileTree],
  );
  const activeOutlinePathIds = React.useMemo(
    () => new Set(activeOutlineId ? getOutlinePathIds(documentOutline, activeOutlineId) : []),
    [activeOutlineId, documentOutline],
  );
  const activeOutlinePath = React.useMemo(
    () => (activeOutlineId ? getOutlinePathIds(documentOutline, activeOutlineId) : []),
    [activeOutlineId, documentOutline],
  );
  const animatedOutlineId =
    activeOutlinePath.length > 0 && animatedPathIndex >= 0
      ? activeOutlinePath[Math.min(animatedPathIndex, activeOutlinePath.length - 1)]
      : "";
  const animatedVirtualPath =
    activeVirtualPathList.length > 0 && animatedPathIndex >= 0
      ? activeVirtualPathList[Math.min(animatedPathIndex, activeVirtualPathList.length - 1)]
      : "";
  const visibleOutlinePathIds = React.useMemo(
    () => new Set(activeOutlinePath.slice(0, Math.max(animatedPathIndex + 1, 0))),
    [activeOutlinePath, animatedPathIndex],
  );
  const visibleVirtualPathIds = React.useMemo(
    () => new Set(activeVirtualPathList.slice(0, Math.max(animatedPathIndex + 1, 0))),
    [activeVirtualPathList, animatedPathIndex],
  );

  const goNext = React.useCallback(() => {
    userInspectingRef.current = false;
    setIsUserInspecting(false);
    lastAutoNavigationKeyRef.current = "";
    setMode("paused");
    setManualOutlineId("");
    setManualVirtualPath("");
    setIndex((current) => getNextVisibleActionIndex(actions, current));
  }, [actions]);

  const jumpToReplayAction = React.useCallback((actionIndex: number) => {
    userInspectingRef.current = true;
    setIsUserInspecting(true);
    setMode("paused");
    lastAutoNavigationKeyRef.current = "";
    setManualOutlineId("");
    setManualVirtualPath("");
    setAnimatedPathIndex(-1);
    setIndex(Math.max(0, Math.min(actionIndex, Math.max(actions.length - 1, 0))));
  }, [actions.length]);

  const playSingleReplayAction = React.useCallback((actionIndex: number) => {
    userInspectingRef.current = false;
    setIsUserInspecting(false);
    setMode("paused");
    lastAutoNavigationKeyRef.current = "";
    setManualOutlineId("");
    setManualVirtualPath("");
    setAnimatedPathIndex(-1);
    setIndex(Math.max(0, Math.min(actionIndex, Math.max(actions.length - 1, 0))));
    setSingleReplayTick((current) => current + 1);
  }, [actions.length]);

  React.useEffect(() => {
    clearReadingLineHighlight(iframeRef.current);
    applyHighlights(iframeRef.current, highlights, isFieldWriteActionType(currentActionType));
  }, [currentActionType, highlights, index]);

  React.useEffect(() => {
    const stream = agentStreamRef.current;
    if (stream) {
      stream.scrollTop = stream.scrollHeight;
    }
  }, [index]);

  React.useEffect(() => {
    const animationIframe = iframeRef.current;
    let cancelled = false;
    if (userInspectingRef.current) {
      return;
    }
    const wait = (ms: number) =>
      new Promise<void>((resolve) => {
        window.setTimeout(resolve, Math.max(0, ms / Math.max(speed, 0.1)));
      });
    const shouldStop = () => cancelled || userInspectingRef.current;
    const advanceAfterAnimation = async () => {
      if (mode !== "auto" || index >= actions.length - 1 || shouldStop()) {
        return;
      }
      await wait(520);
      if (shouldStop()) {
        return;
      }
      setManualOutlineId("");
      setIndex((current) => getNextVisibleActionIndex(actions, current));
    };
    const runAnimation = async () => {
      await wait(0);
      if (shouldStop()) {
        return;
      }
      setAnimatedPathIndex(-1);
      clearReadingLineHighlight(animationIframe);
      applyHighlights(animationIframe, highlights, isFieldWriteActionType(currentActionType));
      await wait(TEXT_READ_DELAY_MS - 260);
      if (shouldStop()) {
        return;
      }
      const readableEvidenceIds = getReadableEvidenceIdsForHighlightState(animationIframe, highlights, highlightAnchorIds, {
        preserveOrder: highlights.preserveReadOrder,
        documentOrder: isFieldWriteActionType(currentActionType),
        fieldWrite: isFieldWriteActionType(currentActionType),
      });
      const navigationSubjectId = usesVirtualFileTree ? activeVirtualPath : activeOutlineId;
      const navigationPath = usesVirtualFileTree ? activeVirtualPathList : activeOutlinePath;
      const navigationKey = getReplayNavigationKey(navigationSubjectId, readableEvidenceIds);
      const shouldReplayOutlinePath = Boolean(isLeftPanelOpen && navigationKey && navigationKey !== lastAutoNavigationKeyRef.current);
      if (navigationKey) {
        lastAutoNavigationKeyRef.current = navigationKey;
      }
      if (shouldReplayOutlinePath) {
        for (let pathIndex = 0; pathIndex < navigationPath.length; pathIndex += 1) {
          await wait(pathIndex === 0 ? 260 : OUTLINE_STEP_MS);
          if (shouldStop()) {
            return;
          }
          const outlineId = navigationPath[pathIndex];
          setAnimatedPathIndex(pathIndex);
          if (usesVirtualFileTree) {
            setExpandedVirtualPaths((current) => {
              const next = new Set(current ?? []);
              next.add(outlineId);
              return next;
            });
          } else {
            setExpandedOutlineIds((current) => {
              const next = new Set(current);
              next.add(outlineId);
              return next;
            });
          }
          const scrollContainer = usesVirtualFileTree ? virtualTreeScrollRef.current : outlineScrollRef.current;
          const pathElement = usesVirtualFileTree
            ? virtualFileRefs.current.get(outlineId) ?? null
            : outlineRefs.current.get(outlineId) ?? null;
          scrollOutlineItemIntoView(scrollContainer, pathElement);
          await wait(140);
          if (shouldStop()) {
            return;
          }
          const point = getElementPointInContainer(
            reviewRef.current,
            pathElement,
          );
          if (point) {
            setReplayCursor((current) => ({
              visible: true,
              x: point.x,
              y: point.y,
              clickTick: current.clickTick,
            }));
          }
          await wait(560);
          if (shouldStop()) {
            return;
          }
          setReplayCursor((current) => ({
            ...current,
            clickTick: current.clickTick + 1,
          }));
          await wait(280);
        }
      }
      for (const evidenceId of readableEvidenceIds) {
        if (shouldStop()) {
          return;
        }
        scrollToEvidence(animationIframe, evidenceId);
        await wait(DOCUMENT_READ_DELAY_MS);
        if (shouldStop()) {
          return;
        }
        const readMode = getEvidenceReadMode(animationIframe, evidenceId);
        if (readMode === "block") {
          highlightEvidenceBlock(animationIframe, evidenceId);
          await wait(getEvidenceBlockReadDuration(animationIframe, evidenceId));
          clearReadingLineHighlight(animationIframe);
          continue;
        }
        const lines = getEvidenceReadingLines(animationIframe, evidenceId);
        for (let lineIndex = 0; lineIndex < lines.length; lineIndex += 1) {
          const line = lines[lineIndex];
          if (shouldStop()) {
            return;
          }
          ensureTextLineVisible(animationIframe, line);
          await wait(210);
          if (shouldStop()) {
            return;
          }
          highlightEvidenceTextLine(animationIframe, evidenceId, line);
          const startPoint = getTextLinePointInContainer(reviewRef.current, animationIframe, line, 0);
          if (startPoint) {
            setReplayCursor((current) => ({
              visible: true,
              x: startPoint.x,
              y: startPoint.y,
              clickTick: current.clickTick,
            }));
          }
          await wait(DOCUMENT_LINE_SCAN_MS);
          if (shouldStop()) {
            return;
          }
          const endPoint = getTextLinePointInContainer(reviewRef.current, animationIframe, line, 1);
          if (endPoint) {
            setReplayCursor((current) => ({
              visible: true,
              x: endPoint.x,
              y: endPoint.y,
              clickTick: current.clickTick,
            }));
          }
          await wait(DOCUMENT_LINE_SCAN_MS);
        }
        clearReadingLineHighlight(animationIframe);
      }
      clearReadingLineHighlight(animationIframe);
      await advanceAfterAnimation();
    };
    void runAnimation();
    return () => {
      cancelled = true;
      clearReadingLineHighlight(animationIframe);
    };
  }, [
    actions,
    actions.length,
    activeOutlineId,
    activeOutlinePath,
    activeVirtualPath,
    activeVirtualPathList,
    currentActionType,
    highlightAnchorIds,
    highlights,
    index,
    isLeftPanelOpen,
    manualOutlineTick,
    mode,
    singleReplayTick,
    speed,
    usesVirtualFileTree,
  ]);

  function pauseForUserInspection() {
    userInspectingRef.current = true;
    setIsUserInspecting(true);
    setMode("paused");
    clearReadingLineHighlight(iframeRef.current);
  }

  function startPanelResize(side: SidebarResizeSide, event: React.PointerEvent<HTMLButtonElement>) {
    event.preventDefault();
    event.stopPropagation();
    pauseForUserInspection();
    const handle = event.currentTarget;
    const startX = event.clientX;
    if (!Number.isFinite(startX)) {
      return;
    }
    const startWidth = side === "left" ? leftPanelWidth : rightPanelWidth;
    const pointerId = event.pointerId;

    const updateWidth = (clientX: number) => {
      if (!Number.isFinite(clientX)) {
        return;
      }
      const deltaX = clientX - startX;
      if (side === "left") {
        setLeftPanelWidth(clampPanelWidth(startWidth + deltaX, LEFT_PANEL_MIN_WIDTH, LEFT_PANEL_MAX_WIDTH));
        return;
      }
      setRightPanelWidth(clampPanelWidth(startWidth - deltaX, RIGHT_PANEL_MIN_WIDTH, RIGHT_PANEL_MAX_WIDTH));
    };
    const stopResize = () => {
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", handlePointerEnd);
      window.removeEventListener("pointercancel", handlePointerEnd);
      document.body.classList.remove("is-resizing-replay-panel");
      try {
        handle.releasePointerCapture(pointerId);
      } catch {
        // JSDOM 和部分浏览器状态下可能没有已捕获的 pointer。
      }
    };
    const handlePointerMove = (moveEvent: PointerEvent) => {
      moveEvent.preventDefault();
      updateWidth(moveEvent.clientX);
    };
    const handlePointerEnd = (moveEvent: PointerEvent) => {
      moveEvent.preventDefault();
      updateWidth(moveEvent.clientX);
      stopResize();
    };

    document.body.classList.add("is-resizing-replay-panel");
    try {
      handle.setPointerCapture(pointerId);
    } catch {
      // JSDOM 和旧浏览器没有完整 pointer capture，不影响 window 级拖拽监听。
    }
    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", handlePointerEnd);
    window.addEventListener("pointercancel", handlePointerEnd);
  }

  function resizePanelByKeyboard(side: SidebarResizeSide, event: React.KeyboardEvent<HTMLButtonElement>) {
    const keyToDelta: Record<string, number> = {
      ArrowLeft: -PANEL_RESIZE_KEY_STEP,
      ArrowRight: PANEL_RESIZE_KEY_STEP,
    };
    if (event.key === "Home") {
      event.preventDefault();
      pauseForUserInspection();
      if (side === "left") {
        setLeftPanelWidth(LEFT_PANEL_MIN_WIDTH);
      } else {
        setRightPanelWidth(RIGHT_PANEL_MAX_WIDTH);
      }
      return;
    }
    if (event.key === "End") {
      event.preventDefault();
      pauseForUserInspection();
      if (side === "left") {
        setLeftPanelWidth(LEFT_PANEL_MAX_WIDTH);
      } else {
        setRightPanelWidth(RIGHT_PANEL_MIN_WIDTH);
      }
      return;
    }
    const delta = keyToDelta[event.key];
    if (!delta) {
      return;
    }
    event.preventDefault();
    pauseForUserInspection();
    if (side === "left") {
      setLeftPanelWidth((current) => clampPanelWidth(current + delta, LEFT_PANEL_MIN_WIDTH, LEFT_PANEL_MAX_WIDTH));
      return;
    }
    setRightPanelWidth((current) => clampPanelWidth(current - delta, RIGHT_PANEL_MIN_WIDTH, RIGHT_PANEL_MAX_WIDTH));
  }

  function toggleAutoMode() {
    setMode((current) => {
      if (current === "auto") {
        return "paused";
      }
      userInspectingRef.current = false;
      setIsUserInspecting(false);
      lastAutoNavigationKeyRef.current = "";
      setManualOutlineId("");
      setManualVirtualPath("");
      return "auto";
    });
  }

  React.useEffect(() => {
    const iframeDocument = iframeRef.current?.contentDocument;
    if (!iframeDocument) {
      return;
    }
    const handleUserInspect = () => pauseForUserInspection();
    iframeDocument.addEventListener("wheel", handleUserInspect, { passive: true });
    iframeDocument.addEventListener("pointerdown", handleUserInspect);
    iframeDocument.addEventListener("touchstart", handleUserInspect, { passive: true });
    return () => {
      iframeDocument.removeEventListener("wheel", handleUserInspect);
      iframeDocument.removeEventListener("pointerdown", handleUserInspect);
      iframeDocument.removeEventListener("touchstart", handleUserInspect);
    };
  }, [iframeInteractionTick, iframeHtml, replay?.task_id]);

  async function enterBrowserFullscreen() {
    const target = reviewRef.current;
    if (!target || !document.fullscreenEnabled) {
      return;
    }
    if (document.fullscreenElement) {
      await document.exitFullscreen();
      return;
    }
    await target.requestFullscreen();
  }

  function jumpToEvidence(evidenceId: string, options?: { outlineId?: string }) {
    userInspectingRef.current = true;
    setIsUserInspecting(true);
    setMode("paused");
    const virtualPath = getPathFromVirtualEvidenceId(evidenceId);
    const resolvedEvidenceId = resolveVirtualEvidenceId(evidenceId, virtualHtmlAnchors);
    if (usesVirtualFileTree && virtualPath) {
      setManualVirtualPath(virtualPath);
      setExpandedVirtualPaths((current) => {
        const next = new Set(current ?? []);
        for (const pathId of getVirtualPathIds(virtualFileTree, virtualPath)) {
          next.add(pathId);
        }
        return next;
      });
    }
    if (options?.outlineId) {
      setManualOutlineId(options.outlineId);
      setManualOutlineTick((current) => current + 1);
    }
    window.setTimeout(() => scrollToEvidence(iframeRef.current, resolvedEvidenceId), 0);
  }

  function jumpToOutline(outlineId: string) {
    pauseForUserInspection();
    setManualOutlineId(outlineId);
    setManualOutlineTick((current) => current + 1);
    setExpandedOutlineIds((current) => {
      const next = new Set(current);
      for (const pathId of getOutlinePathIds(documentOutline, outlineId)) {
        next.add(pathId);
      }
      return next;
    });
    window.setTimeout(() => {
      scrollOutlineItemIntoView(outlineScrollRef.current, outlineRefs.current.get(outlineId) ?? null);
      scrollToEvidence(iframeRef.current, outlineId);
    }, 0);
  }

  function jumpToVirtualPath(path: string) {
    pauseForUserInspection();
    setManualVirtualPath(path);
    setExpandedVirtualPaths((current) => {
      const next = new Set(current ?? []);
      for (const pathId of getVirtualPathIds(virtualFileTree, path)) {
        next.add(pathId);
      }
      return next;
    });
    window.setTimeout(() => {
      scrollOutlineItemIntoView(virtualTreeScrollRef.current, virtualFileRefs.current.get(path) ?? null);
      const evidenceId = virtualHtmlAnchors.byPath.get(path);
      if (evidenceId) {
        scrollToEvidence(iframeRef.current, evidenceId);
      }
    }, 0);
  }

  if (!replay) {
    return (
      <div className="rounded-md border border-dashed p-8 text-sm text-muted-foreground">
        暂无 replay 数据。
      </div>
    );
  }

  return (
    <section
      ref={reviewRef}
      className={
        visibleFieldWrite
          ? "replay-review-root has-field-write min-h-[calc(100svh-7rem)] space-y-4 bg-background"
          : "replay-review-root min-h-[calc(100svh-7rem)] space-y-4 bg-background"
      }
    >
      <div
        className={isLeftPanelOpen && replayCursor.visible ? "replay-cursor is-visible" : "replay-cursor"}
        style={{ left: replayCursor.x, top: replayCursor.y }}
        aria-hidden="true"
      >
        <MousePointerClick
          key={replayCursor.clickTick}
          className="replay-cursor-icon"
        />
      </div>
      <div className="flex flex-wrap items-start justify-between gap-3 rounded-md border bg-background px-4 py-3 shadow-sm">
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-foreground">
            {replay.documents.map((document) => document.filename).join("、") || replay.task_id}
          </p>
          <div className="mt-1 flex flex-wrap items-center gap-2">
            <Badge variant={mode === "auto" ? "success" : "secondary"}>
              {mode}
            </Badge>
            <span className="text-xs text-muted-foreground">AI extraction replay</span>
          </div>
        </div>
        <span className="font-mono text-xs text-muted-foreground">
          {actions.length === 0 ? "0 / 0" : `${index + 1} / ${actions.length}`}
        </span>
      </div>
      <div
        className="replay-stage grid"
        data-left-panel-open={isLeftPanelOpen ? "true" : "false"}
        style={stageStyle}
      >
        {isLeftPanelOpen ? (
          <aside
            className="replay-outline-panel overflow-hidden rounded-md border bg-background"
            onPointerDown={pauseForUserInspection}
            onWheel={pauseForUserInspection}
            onTouchStart={pauseForUserInspection}
          >
            {usesVirtualFileTree ? (
              <>
                <div className="flex justify-end border-b px-2 py-2">
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7"
                    aria-label="关闭左侧文件树"
                    title="关闭左侧文件树"
                    onClick={() => {
                      setReplayCursor((current) => ({ ...current, visible: false }));
                      setIsLeftPanelOpen(false);
                    }}
                  >
                    <PanelLeftClose className="h-4 w-4" aria-hidden="true" />
                  </Button>
                </div>
                <nav
                  ref={virtualTreeScrollRef}
                  aria-label="虚拟文件树导航"
                  className="h-[calc(100%-2.75rem)] space-y-1 overflow-auto p-3"
                >
                  {virtualFileTree.tree.map((node) => (
                    <VirtualFileTreeNode
                      key={node.path}
                      node={node}
                      activeVirtualPath={activeVirtualPath}
                      animatedVirtualPath={animatedVirtualPath}
                      actionIndex={index + manualOutlineTick}
                      expandedPaths={displayedExpandedVirtualPaths}
                      activePathIds={manualVirtualPath || mode !== "auto" ? activeVirtualPathIds : visibleVirtualPathIds}
                      virtualFileRefs={virtualFileRefs}
                      onJump={jumpToVirtualPath}
                      onToggle={(path) => {
                        setExpandedVirtualPaths((current) => {
                          const next = new Set(current ?? displayedExpandedVirtualPaths);
                          if (next.has(path)) {
                            next.delete(path);
                          } else {
                            next.add(path);
                          }
                          return next;
                        });
                      }}
                    />
                  ))}
                </nav>
              </>
            ) : (
              <>
                <div className="flex justify-end border-b px-2 py-2">
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7"
                    aria-label="关闭左侧文档结构"
                    title="关闭左侧文档结构"
                    onClick={() => {
                      setReplayCursor((current) => ({ ...current, visible: false }));
                      setIsLeftPanelOpen(false);
                    }}
                  >
                    <PanelLeftClose className="h-4 w-4" aria-hidden="true" />
                  </Button>
                </div>
                <div ref={outlineScrollRef} className="h-[calc(100%-2.75rem)] space-y-1 overflow-auto p-3">
                  {documentOutline.tree.length > 0 ? (
                    documentOutline.tree.map((node) => (
                      <OutlineTreeNode
                        key={node.id}
                        node={node}
                        activeOutlineId={activeOutlineId}
                        animatedOutlineId={animatedOutlineId}
                        actionIndex={index + manualOutlineTick}
                        expandedIds={expandedOutlineIds}
                        activePathIds={manualOutlineId || mode !== "auto" ? activeOutlinePathIds : visibleOutlinePathIds}
                        outlineRefs={outlineRefs}
                        onJump={jumpToOutline}
                        onToggle={(id) => {
                          setExpandedOutlineIds((current) => {
                            const next = new Set(current);
                            if (next.has(id)) {
                              next.delete(id);
                            } else {
                              next.add(id);
                            }
                            return next;
                          });
                        }}
                      />
                    ))
                  ) : (
                    <p className="rounded bg-muted px-2 py-3 text-xs text-muted-foreground">
                      没有可用的标题节点。
                    </p>
                  )}
                </div>
              </>
            )}
          </aside>
        ) : null}
        {isLeftPanelOpen ? (
          <PanelResizeHandle
            side="left"
            width={leftPanelWidth}
            onPointerDown={(event) => startPanelResize("left", event)}
            onKeyDown={(event) => resizePanelByKeyboard("left", event)}
          />
        ) : null}

        <div className="relative flex min-h-0 flex-col">
          {!isLeftPanelOpen ? (
            <Button
              type="button"
              variant="outline"
              size="icon"
              className="absolute left-2 top-2 z-10 h-7 w-7 bg-background/90 shadow-sm backdrop-blur"
              aria-label={usesVirtualFileTree ? "打开左侧文件树" : "打开左侧文档结构"}
              title={usesVirtualFileTree ? "打开左侧文件树" : "打开左侧文档结构"}
              onClick={() => setIsLeftPanelOpen(true)}
            >
              <PanelLeftOpen className="h-4 w-4" aria-hidden="true" />
            </Button>
          ) : null}
          <div className="replay-document-panel overflow-hidden bg-white">
            {replay.display_html ? (
              <iframe
                ref={iframeRef}
                title="document replay"
                srcDoc={iframeHtml || replayHtml}
                className="block h-full w-full border-0 bg-white"
                onLoad={() => {
                  applyHighlights(iframeRef.current, highlights, isFieldWriteActionType(currentActionType));
                  setIframeInteractionTick((current) => current + 1);
                }}
              />
            ) : (
              <div className="flex h-full items-center justify-center p-8 text-sm text-muted-foreground">
                document_processor 没有返回 display_html。
              </div>
            )}
          </div>
        </div>

        <PanelResizeHandle
          side="right"
          width={rightPanelWidth}
          onPointerDown={(event) => startPanelResize("right", event)}
          onKeyDown={(event) => resizePanelByKeyboard("right", event)}
        />

        <aside className="replay-agent-panel-slot">
          <section className="replay-agent-panel" aria-label="Agent 工具回放">
            <div className="replay-agent-header">
              <span className="replay-agent-title">AI</span>
              <span className="font-mono text-[11px] text-muted-foreground">
                {visibleActionCount === 0 ? "step 0 of 0" : `step ${agentStreamActions.length} of ${visibleActionCount}`}
              </span>
            </div>
            <div ref={agentStreamRef} className="replay-agent-stream" aria-label="Agent 文字流">
              {agentStreamActions.length > 0 ? (
                agentStreamActions.map(({ action, actionIndex }, visibleIndex) => {
                  const isCurrent = actionIndex === index;
                  const visibleStepNumber = visibleIndex + 1;
                  const reason = formatReasonText(getActionReason(action), documentOutline);
                  const toolName = getActionType(action) || "tool";
                  const target = getActionTarget(action);
                  const result = readObject(action.result);
                  const ok = result?.ok !== false;
                  const showActionControls = hoveredAgentActionIndex === actionIndex;
                  return (
                    <div
                      key={`${actionIndex}-${toolName}-${target}`}
                      aria-label={`第 ${visibleStepNumber} 步 ${toolName}`}
                      className={isCurrent ? "replay-agent-turn is-current" : "replay-agent-turn"}
                      onMouseEnter={() => setHoveredAgentActionIndex(actionIndex)}
                      onMouseLeave={() => setHoveredAgentActionIndex((current) => (current === actionIndex ? null : current))}
                      onFocus={() => setHoveredAgentActionIndex(actionIndex)}
                      onBlur={(event) => {
                        if (!event.currentTarget.contains(event.relatedTarget)) {
                          setHoveredAgentActionIndex((current) => (current === actionIndex ? null : current));
                        }
                      }}
                    >
                      {reason ? (
                        <button
                          type="button"
                          className="replay-agent-message"
                          onClick={goNext}
                        >
                          <span className="replay-agent-reason-text">{reason}</span>
                        </button>
                      ) : null}
                      <AgentToolLine action={action} ok={ok} onClick={goNext} />
                      {showActionControls ? (
                        <div className="replay-agent-turn-controls">
                          <Button
                            type="button"
                            variant="outline"
                            size="icon"
                            className="h-7 w-7"
                            aria-label={`跳到第 ${visibleStepNumber} 步`}
                            onClick={(event) => {
                              event.stopPropagation();
                              jumpToReplayAction(actionIndex);
                            }}
                          >
                            <MousePointerClick className="h-4 w-4" />
                          </Button>
                          <Button
                            type="button"
                            variant="outline"
                            size="icon"
                            className="h-7 w-7"
                            aria-label={`只播放第 ${visibleStepNumber} 步`}
                            onClick={(event) => {
                              event.stopPropagation();
                              playSingleReplayAction(actionIndex);
                            }}
                          >
                            <Play className="h-4 w-4" />
                          </Button>
                        </div>
                      ) : null}
                    </div>
                  );
                })
              ) : (
                <div className="replay-agent-turn is-current">
                  <div className="replay-agent-empty">等待工具调用。</div>
                </div>
              )}
            </div>
            {visibleFieldWrite ? (
              <div className="replay-agent-review-shell">
                <ReplayFieldWriteCard
                  key={`field-${index}-${visibleFieldWrite.sourceName}`}
                  field={visibleFieldWrite}
                  documentOutline={documentOutline}
                  reviewValue={
                    reviewValues[visibleFieldWrite.sourceName] ??
                    visibleFieldWrite.reviewField?.agent_value ??
                    stringifyValue(visibleFieldWrite.value)
                  }
                  reviewComment={reviewComment}
                  isSubmittingReview={isSubmittingReview}
                  onJumpToEvidence={jumpToEvidence}
                  onReviewValueChange={onReviewValueChange}
                  onReviewCommentChange={onReviewCommentChange}
                  onSubmitReview={onSubmitReview}
                />
              </div>
            ) : null}
            <div className="replay-agent-controls">
              <Button
                type="button"
                variant={mode === "auto" ? "default" : "outline"}
                size="icon"
                onClick={toggleAutoMode}
                disabled={actions.length === 0}
                aria-label={mode === "auto" ? "暂停自动播放" : "自动播放"}
              >
                {mode === "auto" ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
              </Button>
              <Button
                type="button"
                variant="outline"
                size="icon"
                onClick={goNext}
                disabled={actions.length === 0}
                aria-label="下一步"
              >
                <ChevronRight className="h-4 w-4" />
              </Button>
              <div className="replay-speed-control">
                <Button type="button" variant="outline" size="icon" aria-label="播放速度">
                  <Gauge className="h-4 w-4" />
                </Button>
                <label className="replay-speed-popover">
                  <input
                    type="range"
                    min="0.25"
                    max="2"
                    step="0.25"
                    value={speed}
                    onChange={(event) => setSpeed(Number(event.currentTarget.value))}
                  />
                  <span className="font-mono text-xs">{speed}x</span>
                </label>
              </div>
              <Button
                type="button"
                variant="outline"
                size="icon"
                onClick={() => void enterBrowserFullscreen()}
                aria-label="全屏视图"
              >
                <Expand className="h-4 w-4" />
              </Button>
              {mode === "auto" ? <Loader2 className="h-4 w-4 animate-spin text-primary" /> : null}
              <span className="ml-auto font-mono text-xs text-muted-foreground">
                {actions.length === 0 ? "0/0" : `${index + 1}/${actions.length}`}
              </span>
            </div>
          </section>
        </aside>

      </div>
    </section>
  );
}

function PanelResizeHandle({
  side,
  width,
  onPointerDown,
  onKeyDown,
}: {
  side: SidebarResizeSide;
  width: number;
  onPointerDown: (event: React.PointerEvent<HTMLButtonElement>) => void;
  onKeyDown: (event: React.KeyboardEvent<HTMLButtonElement>) => void;
}) {
  const isLeft = side === "left";
  return (
    <button
      type="button"
      role="separator"
      aria-label={isLeft ? "调整左侧栏宽度" : "调整右侧栏宽度"}
      aria-orientation="vertical"
      aria-valuemin={isLeft ? LEFT_PANEL_MIN_WIDTH : RIGHT_PANEL_MIN_WIDTH}
      aria-valuemax={isLeft ? LEFT_PANEL_MAX_WIDTH : RIGHT_PANEL_MAX_WIDTH}
      aria-valuenow={width}
      className="replay-panel-resize-handle"
      title={isLeft ? "调整左侧栏宽度" : "调整右侧栏宽度"}
      onPointerDown={onPointerDown}
      onKeyDown={onKeyDown}
    >
      <span className="replay-panel-resize-grip" aria-hidden="true" />
    </button>
  );
}

function ReplayFieldRouteBadge({ field }: { field: ReplayField }) {
  if (field.route === "accept") {
    return <Badge variant="success">accept</Badge>;
  }
  if (field.route === "review") {
    return <Badge variant="warning">review</Badge>;
  }
  if (field.route === "reject") {
    return <Badge variant="destructive">reject</Badge>;
  }
  return <Badge variant="outline">{field.route}</Badge>;
}

function AgentToolLine({
  action,
  ok,
  onClick,
}: {
  action: ReplayAction;
  ok: boolean;
  onClick: () => void;
}) {
  const toolName = getActionType(action) || "tool";
  const summary = formatAgentToolSummary(action, ok);
  const meta = collectAgentToolMeta(action, ok);
  const isReadTool = isReadToolName(toolName);
  const ToolIcon = isReadTool ? Search : SquareTerminal;
  const lineText = [summary, ...meta].filter(Boolean).join(" · ");
  return (
    <button
      type="button"
      className={[
        "replay-agent-tool-line",
        isReadTool ? "is-read-tool" : "",
        ok ? "" : "is-failed",
      ].filter(Boolean).join(" ")}
      aria-label={`tool ${toolName}`}
      data-tool-icon={isReadTool ? "search" : "terminal"}
      onClick={onClick}
    >
      <ToolIcon className="replay-agent-tool-icon" aria-hidden="true" />
      <span className="replay-agent-tool-summary">{lineText}</span>
    </button>
  );
}

function isReadToolName(toolName: string): boolean {
  return toolName === "read" || toolName === "read_element" || toolName === "read_section";
}

function shouldDisplayAgentAction(action: ReplayAction): boolean {
  return getActionType(action) !== "anchors";
}

function clampPanelWidth(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, Math.round(value)));
}

function getNextVisibleActionIndex(actions: ReplayAction[], currentIndex: number): number {
  if (actions.length === 0) {
    return 0;
  }
  for (let actionIndex = Math.min(currentIndex + 1, actions.length - 1); actionIndex < actions.length; actionIndex += 1) {
    if (shouldDisplayAgentAction(actions[actionIndex])) {
      return actionIndex;
    }
  }
  for (let actionIndex = Math.min(currentIndex, actions.length - 1); actionIndex >= 0; actionIndex -= 1) {
    if (shouldDisplayAgentAction(actions[actionIndex])) {
      return actionIndex;
    }
  }
  return Math.max(0, Math.min(currentIndex, actions.length - 1));
}

function formatAgentToolSummary(action: ReplayAction, ok: boolean): string {
  const toolName = getActionType(action) || "tool";
  const args = readObject(action.args);
  const result = readObject(action.result);
  const resultField = readObject(result?.field);
  const path = readString(args?.path) || readString(result?.path) || readString(resultField?.path);
  const field = readString(args?.field_id) || readString(result?.field_id) || readString(resultField?.field_id) || readString(args?.name) || readString(resultField?.name);
  const target = readString(args?.element_id) || readString(args?.section_id) || readString(args?.table_id) || readString(result?.id) || readString(result?.table_id);
  const query = readString(args?.query) || readString(result?.query);
  const baseName = path ? getPathBasename(path) : "";
  if (toolName === "tree") {
    return `Ran tree ${path || "/"}`;
  }
  if (toolName === "read" || toolName === "read_element" || toolName === "read_section") {
    const readKind = getReadActionKind(action);
    const readLabel = formatReadTargetLabel(path) || target || "document";
    return `Read ${readKind} ${readLabel}`;
  }
  if (toolName === "anchors") {
    return `Found anchors in ${baseName || "paragraph"}`;
  }
  if (toolName === "query_table") {
    return ok ? `Queried ${baseName || "table"}` : "查询失败";
  }
  if (toolName === "table_extraction" || toolName === "custom_extraction") {
    if (!ok) {
      return "查询失败";
    }
    const rows = Array.isArray(result?.rows) ? result.rows : [];
    const rowCount = readNumber(result?.row_count);
    if (rows.length === 0 && rowCount === 0) {
      return "未查到结果";
    }
    return `Queried ${target || "table"}`;
  }
  if (toolName === "search_elements") {
    return query ? `Searched for ${query}` : "Searched document";
  }
  if (toolName === "bind_evidence") {
    return field ? `Bound evidence for ${field}` : "Bound evidence";
  }
  if (toolName === "review_field") {
    return field ? `Reviewed ${field}` : "Reviewed field";
  }
  if (toolName === "write_field" || toolName === "set_field") {
    return field ? `Wrote ${field}` : "Wrote field";
  }
  if (toolName === "submit_result") {
    return ok ? "Submitted result" : "Submit failed";
  }
  if (path) {
    return baseName || path;
  }
  if (field) {
    return field;
  }
  if (target) {
    return target;
  }
  return ok ? "Ran tool" : "Tool failed";
}

function collectAgentToolMeta(action: ReplayAction, ok: boolean): string[] {
  const toolName = getActionType(action);
  const args = readObject(action.args);
  const result = readObject(action.result);
  const meta: string[] = [];
  const add = (value: unknown, suffix = "") => {
    const text = readString(value);
    if (text) {
      meta.push(`${text}${suffix}`);
    }
  };
  if (toolName === "search_elements") {
    const count = readNumber(result?.match_count);
    if (count !== null) {
      meta.push(`${count} match${count === 1 ? "" : "es"}`);
    }
  }
  if (toolName === "query_table") {
    const count = readNumber(result?.total) ?? readNumber(result?.matched_rows) ?? readNumber(result?.row_count);
    if (count !== null && ok) {
      meta.push(`${count} row${count === 1 ? "" : "s"}`);
    }
    if (!ok) {
      add(result?.error || "query_table failed");
    }
  }
  if (toolName === "table_extraction" || toolName === "custom_extraction") {
    const rows = Array.isArray(result?.rows) ? result.rows.length : readNumber(result?.row_count);
    if (typeof rows === "number" && ok) {
      meta.push(`${rows} row${rows === 1 ? "" : "s"}`);
    }
    if (!ok) {
      add(result?.error || "table query failed");
    }
    if (ok && rows === 0) {
      meta.push("没有查到匹配行。");
    }
  }
  add(args?.limit, " limit");
  return meta.slice(0, 2);
}

function getReadActionKind(action: ReplayAction): string {
  const args = readObject(action.args);
  const result = readObject(action.result);
  const resultField = readObject(result?.field);
  const path = readString(args?.path) || readString(result?.path) || readString(resultField?.path);
  const kind = readString(result?.kind).toLowerCase();
  if (kind.includes("table") || /\.table$/i.test(path)) {
    return "table";
  }
  if (kind.includes("list") || /\.list$/i.test(path)) {
    return "list";
  }
  if (kind.includes("paragraph") || /\.md$/i.test(path)) {
    return "paragraph";
  }
  return "document";
}

function formatReadTargetLabel(path: string): string {
  if (!path) {
    return "";
  }
  return getPathBasename(path)
    .replace(/\.(md|table|list)$/i, "")
    .replace(/^\d+-/, "");
}

function getPathBasename(path: string): string {
  return path.split("/").filter(Boolean).at(-1) || path;
}

function ReplayFieldWriteCard({
  field,
  documentOutline,
  reviewValue,
  reviewComment,
  isSubmittingReview,
  onJumpToEvidence,
  onReviewValueChange,
  onReviewCommentChange,
  onSubmitReview,
}: {
  field: ReplayField;
  documentOutline: DocumentOutline;
  reviewValue: unknown;
  reviewComment: string;
  isSubmittingReview: boolean;
  onJumpToEvidence: (evidenceId: string) => void;
  onReviewValueChange?: (fieldName: string, value: unknown) => void;
  onReviewCommentChange?: (value: string) => void;
  onSubmitReview?: () => void;
}) {
  const valueText = formatFieldDisplayValue(field);
  return (
    <div
      className="replay-field-write"
      aria-label="字段写入卡"
      onClick={(event) => event.stopPropagation()}
      onPointerDown={(event) => event.stopPropagation()}
      onWheel={(event) => event.stopPropagation()}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="replay-field-write-title">写入字段：{field.fieldName}</div>
        {field.route ? <ReplayFieldRouteBadge field={field} /> : null}
      </div>
      <div className="replay-field-write-body" aria-label="字段写入内容">
        <div className="replay-field-write-value">
          {valueText || <span className="text-muted-foreground">等待人工补录</span>}
        </div>
        {field.routeReason ? (
          <div className="replay-field-route-reason">{field.routeReason}</div>
        ) : null}
        {field.evidenceIds.length > 0 ? (
          <div className="replay-field-evidence">
            {field.evidenceIds.map((evidenceId) => (
              <button
                key={evidenceId}
                type="button"
                className="replay-field-evidence-chip"
                title={formatEvidenceLabel(evidenceId, documentOutline)}
                onClick={(event) => {
                  event.stopPropagation();
                  onJumpToEvidence(evidenceId);
                }}
              >
                {formatEvidenceLabel(evidenceId, documentOutline)}
              </button>
            ))}
          </div>
        ) : null}
      </div>
      {field.needsReview ? (
        <InlineFieldReviewEditor
          field={field}
          value={reviewValue}
          comment={reviewComment}
          isSubmitting={isSubmittingReview}
          onValueChange={onReviewValueChange}
          onCommentChange={onReviewCommentChange}
          onSubmit={onSubmitReview}
        />
      ) : null}
    </div>
  );
}

function InlineFieldReviewEditor({
  field,
  value,
  comment,
  isSubmitting,
  onValueChange,
  onCommentChange,
  onSubmit,
}: {
  field: ReplayField;
  value: unknown;
  comment: string;
  isSubmitting: boolean;
  onValueChange?: (fieldName: string, value: unknown) => void;
  onCommentChange?: (value: string) => void;
  onSubmit?: () => void;
}) {
  const editorValue = normalizeReviewEditorValue(field, value);
  return (
    <div className="replay-inline-review" aria-label="字段复核区" onClick={(event) => event.stopPropagation()}>
      <div className="space-y-2">
        {isEnumReviewField(field) ? (
          <EnumFieldReviewEditor
            field={field}
            value={editorValue}
            onValueChange={onValueChange}
          />
        ) : (
          <>
            <Label htmlFor={`review-${field.sourceName}`} className="text-xs">
              {field.fieldName} 复核值
            </Label>
            <Textarea
              id={`review-${field.sourceName}`}
              value={stringifyValue(editorValue)}
              onChange={(event) => onValueChange?.(field.sourceName, event.currentTarget.value)}
              className="min-h-16 text-xs"
            />
          </>
        )}
      </div>
      <div className="space-y-2">
        <Label htmlFor="review-comment" className="text-xs">
          复核备注
        </Label>
        <Textarea
          id="review-comment"
          value={comment}
          onChange={(event) => onCommentChange?.(event.currentTarget.value)}
          className="min-h-12 text-xs"
        />
      </div>
      <Button type="button" className="w-full" onClick={onSubmit} disabled={isSubmitting}>
        {isSubmitting ? "提交中..." : "提交修正并通过"}
      </Button>
    </div>
  );
}

function EnumFieldReviewEditor({
  field,
  value,
  onValueChange,
}: {
  field: ReplayField;
  value: unknown;
  onValueChange?: (fieldName: string, value: unknown) => void;
}) {
  const enumValue = toEnumReviewValue(field, value);
  const selectedVariant = enumValue.variant;
  const selectedDefinition = field.variants.find((variant) => variant.name === selectedVariant) ?? field.variants[0];
  const payloadType = selectedDefinition?.type ?? null;
  const payloadId = `review-${field.sourceName}-payload`;
  const variantId = `review-${field.sourceName}-variant`;
  const hasVariants = field.variants.length > 0;

  return (
    <div className="space-y-2">
      <Label htmlFor={`review-${field.sourceName}`} className="text-xs">
        {field.fieldName} 枚举选项
      </Label>
      {hasVariants ? (
        <select
          id={`review-${field.sourceName}`}
          aria-label={`${field.fieldName} 枚举选项`}
          value={selectedVariant}
          onChange={(event) => {
            const nextVariant = field.variants.find((variant) => variant.name === event.currentTarget.value);
            onValueChange?.(field.sourceName, {
              variant: event.currentTarget.value,
              value: defaultEnumPayloadValue(nextVariant?.type)
            });
          }}
          className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-xs shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {field.variants.map((variant) => (
            <option key={variant.name} value={variant.name}>
              {variant.name}
            </option>
          ))}
        </select>
      ) : (
        <Input
          id={variantId}
          aria-label={`${field.fieldName} 枚举选项`}
          value={selectedVariant}
          onChange={(event) =>
            onValueChange?.(field.sourceName, {
              variant: event.currentTarget.value,
              value: enumValue.value
            })
          }
          className="h-9 text-xs"
        />
      )}
      {selectedDefinition?.description ? (
        <p className="text-xs leading-5 text-muted-foreground">{selectedDefinition.description}</p>
      ) : null}
      {payloadType !== null ? (
        <div className="space-y-2">
          <Label htmlFor={payloadId} className="text-xs">
            {selectedVariant} payload
          </Label>
          <Textarea
            id={payloadId}
            value={stringifyValue(enumValue.value)}
            onChange={(event) =>
              onValueChange?.(field.sourceName, {
                variant: selectedVariant,
                value: parseEnumPayloadValue(payloadType, event.currentTarget.value)
              })
            }
            className="min-h-14 text-xs"
          />
        </div>
      ) : !hasVariants ? (
        <div className="space-y-2">
          <Label htmlFor={payloadId} className="text-xs">
            {selectedVariant} payload
          </Label>
          <Textarea
            id={payloadId}
            value={stringifyValue(enumValue.value)}
            onChange={(event) =>
              onValueChange?.(field.sourceName, {
                variant: selectedVariant,
                value: parseLooseJsonValue(event.currentTarget.value)
              })
            }
            className="min-h-14 text-xs"
          />
        </div>
      ) : null}
    </div>
  );
}

function isEnumReviewField(field: ReplayField): boolean {
  return field.fieldType === "enum" || isTaggedEnumValue(field.value);
}

function toEnumReviewValue(field: ReplayField, value: unknown): { variant: string; value: unknown } {
  if (isTaggedEnumValue(value)) {
    return {
      variant: field.variants.some((variant) => variant.name === value.variant) ? value.variant : field.variants[0]?.name || "",
      value: value.value,
    };
  }
  const fallbackVariant = field.variants[0]?.name || "";
  return {
    variant: fallbackVariant,
    value: value,
  };
}

function normalizeReviewEditorValue(field: ReplayField, value: unknown): unknown {
  if (isEnumReviewField(field)) {
    return toEnumReviewValue(field, value);
  }
  return value;
}

function formatFieldDisplayValue(field: ReplayField): string {
  if (isTaggedEnumValue(field.value)) {
    return `${field.value.variant}${field.value.value === null ? "" : `: ${stringifyValue(field.value.value)}`}`;
  }
  return stringifyValue(field.value);
}

function isTaggedEnumValue(value: unknown): value is { variant: string; value: unknown } {
  return (
    value !== null &&
    typeof value === "object" &&
    !Array.isArray(value) &&
    "variant" in value &&
    typeof (value as { variant?: unknown }).variant === "string" &&
    "value" in value
  );
}

function defaultEnumPayloadValue(type?: string | null): unknown {
  if (type === "string") {
    return "";
  }
  if (type === "number") {
    return 0;
  }
  if (type === "boolean") {
    return false;
  }
  if (type === "list[string]" || type === "list[number]") {
    return [];
  }
  return null;
}

function parseEnumPayloadValue(type: string, raw: string): unknown {
  if (type === "string") {
    return raw;
  }
  if (type === "number") {
    const parsed = Number(raw);
    return Number.isFinite(parsed) ? parsed : raw;
  }
  if (type === "boolean") {
    return raw === "true";
  }
  if (type === "list[string]" || type === "list[number]") {
    try {
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed : raw;
    } catch {
      return raw;
    }
  }
  return raw;
}

function parseLooseJsonValue(raw: string): unknown {
  try {
    return JSON.parse(raw);
  } catch {
    return raw;
  }
}

export function HumanReviewEditor({
  fields,
  values,
  comment,
  isSubmitting,
  onValueChange,
  onCommentChange,
  onSubmit,
}: {
  fields: Array<{
    field_name: string;
    display_name?: string | null;
    agent_value: unknown;
    needs_review: boolean;
  }>;
  values: Record<string, string>;
  comment: string;
  isSubmitting: boolean;
  onValueChange: (fieldName: string, value: string) => void;
  onCommentChange: (value: string) => void;
  onSubmit: () => void;
}) {
  const reviewFields = fields.filter((field) => field.needs_review);
  if (reviewFields.length === 0) {
    return null;
  }
  return (
    <section className="rounded-md border bg-card p-3">
      <div className="mb-3">
        <h2 className="text-sm font-semibold text-foreground">人工复核</h2>
        <p className="mt-1 text-xs text-muted-foreground">需要人工接管的字段可以直接修正。</p>
      </div>
      <div className="space-y-3">
        {reviewFields.map((field) => (
          <div key={field.field_name} className="space-y-2">
            <Label htmlFor={`review-${field.field_name}`} className="text-xs">
              {field.display_name || field.field_name}
            </Label>
            <Textarea
              id={`review-${field.field_name}`}
              value={values[field.field_name] ?? stringifyValue(field.agent_value)}
              onChange={(event) => onValueChange(field.field_name, event.currentTarget.value)}
              className="min-h-20 text-xs"
            />
          </div>
        ))}
        <div className="space-y-2">
          <Label htmlFor="review-comment" className="text-xs">复核备注</Label>
          <Textarea
            id="review-comment"
            value={comment}
            onChange={(event) => onCommentChange(event.currentTarget.value)}
            className="min-h-16 text-xs"
          />
        </div>
        <Button type="button" className="w-full" onClick={onSubmit} disabled={isSubmitting}>
          {isSubmitting ? "提交中..." : "提交修正并通过"}
        </Button>
      </div>
    </section>
  );
}

function OutlineTreeNode({
  node,
  activeOutlineId,
  animatedOutlineId,
  actionIndex,
  expandedIds,
  activePathIds,
  outlineRefs,
  onJump,
  onToggle,
}: {
  node: DocumentOutlineNode;
  activeOutlineId: string;
  animatedOutlineId: string;
  actionIndex: number;
  expandedIds: Set<string>;
  activePathIds: Set<string>;
  outlineRefs: React.RefObject<Map<string, HTMLButtonElement>>;
  onJump: (id: string) => void;
  onToggle: (id: string) => void;
}) {
  const isActive = node.id === activeOutlineId;
  const isAnimated = node.id === animatedOutlineId;
  const isExpanded = expandedIds.has(node.id) || activePathIds.has(node.id);
  const hasChildren = node.children.length > 0;
  const handleOpen = () => {
    if (hasChildren) {
      onToggle(node.id);
    }
    onJump(node.id);
  };

  return (
    <div>
      <button
        ref={(element) => {
          if (element) {
            outlineRefs.current.set(node.id, element);
          } else {
            outlineRefs.current.delete(node.id);
          }
        }}
        type="button"
        className={
          isActive
            ? "outline-item-active relative flex w-full items-center gap-1 rounded-md border border-primary bg-accent px-1.5 py-1.5 text-left text-xs font-medium text-accent-foreground"
            : "relative flex w-full items-center gap-1 rounded-md border border-transparent px-1.5 py-1.5 text-left text-xs text-muted-foreground hover:bg-accent hover:text-accent-foreground"
        }
        title={hasChildren ? `${node.label}（点击展开/折叠）` : node.label}
        onClick={handleOpen}
      >
        <span className="min-w-0 flex-1 truncate">
          {isActive || isAnimated ? (
            <span key={`${node.id}-${actionIndex}`} className="outline-item-flash">
              {node.label}
            </span>
          ) : (
            node.label
          )}
        </span>
        {hasChildren ? (
          <ChevronRight
            className={
              isExpanded
                ? "h-3.5 w-3.5 shrink-0 rotate-90 transition-transform"
                : "h-3.5 w-3.5 shrink-0 transition-transform"
            }
          />
        ) : null}
        {isAnimated ? (
          <span key={`click-${node.id}-${actionIndex}`} className="outline-click-target" aria-hidden="true" />
        ) : null}
      </button>
      {hasChildren && isExpanded ? (
        <div className="ml-4 border-l border-border/80 pl-2">
          {node.children.map((child) => (
            <OutlineTreeNode
              key={child.id}
              node={child}
              activeOutlineId={activeOutlineId}
              animatedOutlineId={animatedOutlineId}
              actionIndex={actionIndex}
              expandedIds={expandedIds}
              activePathIds={activePathIds}
              outlineRefs={outlineRefs}
              onJump={onJump}
              onToggle={onToggle}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}

function VirtualFileTreeNode({
  node,
  activeVirtualPath,
  animatedVirtualPath,
  actionIndex,
  expandedPaths,
  activePathIds,
  virtualFileRefs,
  onJump,
  onToggle,
}: {
  node: VirtualFileNode;
  activeVirtualPath: string;
  animatedVirtualPath: string;
  actionIndex: number;
  expandedPaths: Set<string>;
  activePathIds: Set<string>;
  virtualFileRefs: React.RefObject<Map<string, HTMLButtonElement>>;
  onJump: (path: string) => void;
  onToggle: (path: string) => void;
}) {
  const hasChildren = node.children.length > 0;
  const isActive = node.path === activeVirtualPath;
  const isAnimated = node.path === animatedVirtualPath;
  const isExpanded = expandedPaths.has(node.path);
  const isActivePath = !isActive && activePathIds.has(node.path);
  const className = [
    "virtual-file-item relative flex w-full items-center gap-1.5 rounded-md border px-1.5 py-1.5 text-left text-xs transition-colors",
    isActive
      ? "virtual-file-item-active border-primary bg-accent font-medium text-accent-foreground"
      : isActivePath
        ? "virtual-file-item-active-path border-transparent bg-accent/60 text-foreground"
        : "border-transparent text-muted-foreground hover:bg-accent hover:text-accent-foreground",
  ].join(" ");

  return (
    <div>
      <button
        ref={(element) => {
          if (element) {
            virtualFileRefs.current.set(node.path, element);
          } else {
            virtualFileRefs.current.delete(node.path);
          }
        }}
        type="button"
        aria-label={node.displayLabel}
        aria-expanded={hasChildren ? isExpanded : undefined}
        className={className}
        title={node.path}
        onClick={() => {
          if (hasChildren) {
            onToggle(node.path);
            return;
          }
          onJump(node.path);
        }}
      >
        {hasChildren ? (
          <ChevronRight
            className={
              isExpanded
                ? "h-3.5 w-3.5 shrink-0 rotate-90 transition-transform"
                : "h-3.5 w-3.5 shrink-0 transition-transform"
            }
          />
        ) : (
          <span className="virtual-file-leaf-dot" aria-hidden="true" />
        )}
        <span className="min-w-0 flex-1 truncate">
          {isActive || isAnimated ? (
            <span key={`${node.path}-${actionIndex}`} className="outline-item-flash">
              {node.displayLabel}
            </span>
          ) : (
            node.displayLabel
          )}
        </span>
        {isAnimated ? (
          <span key={`click-${node.path}-${actionIndex}`} className="outline-click-target" aria-hidden="true" />
        ) : null}
      </button>
      {hasChildren && isExpanded ? (
        <div className="ml-4 border-l border-border/80 pl-2">
          {node.children.map((child) => (
            <VirtualFileTreeNode
              key={child.path}
              node={child}
              activeVirtualPath={activeVirtualPath}
              animatedVirtualPath={animatedVirtualPath}
              actionIndex={actionIndex}
              expandedPaths={expandedPaths}
              activePathIds={activePathIds}
              virtualFileRefs={virtualFileRefs}
              onJump={onJump}
              onToggle={onToggle}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}

function buildVirtualFileTree(actions: ReplayAction[]): VirtualFileTree {
  const root: VirtualFileNode = {
    path: "/",
    label: "/",
    displayLabel: "/",
    kind: "root",
    children: [],
  };
  const byPath = new Map<string, VirtualFileNode>([["/", root]]);
  const parentByPath = new Map<string, string>();

  const addPath = (rawPath: string) => {
    const normalized = normalizeVirtualPath(rawPath);
    if (!normalized || normalized === "/") {
      return;
    }
    const parts = normalized.split("/").filter(Boolean);
    let parent = root;
    let currentPath = "";
    for (let index = 0; index < parts.length; index += 1) {
      const label = parts[index];
      currentPath = `${currentPath}/${label}`;
      const isLeaf = index === parts.length - 1;
      const existing = byPath.get(currentPath);
      if (existing) {
        if (isLeaf && existing.children.length === 0 && inferVirtualFileKind(label) === "file") {
          existing.kind = "file";
        }
        parent = existing;
        continue;
      }
      const kind = isLeaf ? inferVirtualFileKind(label) : "folder";
      const node: VirtualFileNode = {
        path: currentPath,
        label,
        displayLabel: formatVirtualOutlineLabel(label, kind),
        kind,
        children: [],
      };
      byPath.set(currentPath, node);
      parentByPath.set(currentPath, parent.path);
      parent.children.push(node);
      parent = node;
    }
  };

  for (const action of actions) {
    for (const path of collectVirtualPathsFromAction(action)) {
      addPath(path);
    }
    const result = readObject(action.result);
    if (getActionType(action) === "tree") {
      for (const path of parseVirtualTreePaths(readString(result?.text))) {
        addPath(path);
      }
    }
  }

  return {
    tree: root.children,
    byPath,
    parentByPath,
    allPaths: Array.from(byPath.keys()),
  };
}

function buildVirtualHtmlAnchors(
  displayHtml: string,
  virtualFileTree: VirtualFileTree,
  actions: ReplayAction[],
  inlineAnchors: InlineEvidenceAnchor[] = [],
): VirtualHtmlAnchors {
  const anchors: VirtualHtmlAnchors = {
    byPath: new Map(),
    byVirtualId: new Map(),
    bySelector: new Map(),
  };
  if (!displayHtml.trim() || typeof window === "undefined") {
    return anchors;
  }
  const document = new DOMParser().parseFromString(displayHtml, "text/html");
  for (const inlineAnchor of inlineAnchors) {
    const normalizedPath = normalizeVirtualPath(inlineAnchor.path);
    if (!inlineAnchor.matched || !normalizedPath || !inlineAnchor.selector || !virtualFileTree.byPath.has(normalizedPath)) {
      continue;
    }
    anchors.byVirtualId.set(makeVirtualEvidenceId(normalizedPath, inlineAnchor.selector), inlineAnchor.id);
    if (!anchors.bySelector.has(inlineAnchor.selector)) {
      anchors.bySelector.set(inlineAnchor.selector, inlineAnchor.id);
    }
  }
  const elements = Array.from(document.body.querySelectorAll<HTMLElement>("[id]"))
    .map((element) => ({
      id: element.id,
      text: normalizeVirtualText(element.textContent || ""),
    }))
    .filter((element) => element.id && element.text);

  const remember = (path: string, selector: string, text: string) => {
    const normalizedPath = normalizeVirtualPath(path);
    if (!normalizedPath || !virtualFileTree.byPath.has(normalizedPath)) {
      return;
    }
    const htmlId = findMatchingHtmlElementId(elements, text);
    if (!htmlId) {
      return;
    }
    if (selector) {
      const virtualId = makeVirtualEvidenceId(normalizedPath, selector);
      if (!anchors.byVirtualId.has(virtualId)) {
        anchors.byVirtualId.set(virtualId, htmlId);
      }
      if (!anchors.bySelector.has(selector)) {
        anchors.bySelector.set(selector, htmlId);
      }
    }
    if (!anchors.byPath.has(normalizedPath)) {
      anchors.byPath.set(normalizedPath, htmlId);
    }
  };

  for (const action of actions) {
    const args = readObject(action.args);
    const result = readObject(action.result);
    const resultField = readObject(result?.field);
    for (const item of collectVirtualEvidenceTexts(action)) {
      remember(item.path, item.selector, item.text);
    }
    const actionPath = readString(result?.path) || readString(args?.path) || readString(resultField?.path);
    const actionText = readString(result?.text) || readString(args?.text);
    if (actionPath && actionText) {
      remember(actionPath, "", actionText);
    }
    if (actionPath && getActionType(action) === "anchors") {
      for (const anchor of readObjectArray(result?.anchors)) {
        remember(actionPath, readString(anchor.id), readString(anchor.preview));
      }
    }
  }

  return anchors;
}

function resolveVirtualHighlightState(state: HighlightState, anchors: VirtualHtmlAnchors): HighlightState {
  return {
    currentIds: resolveVirtualEvidenceIds(state.currentIds, anchors),
    tableReferenceIds: resolveVirtualEvidenceIds(state.tableReferenceIds, anchors),
    tableRowIds: resolveVirtualEvidenceIds(state.tableRowIds, anchors),
    readIds: resolveVirtualEvidenceIds(state.readIds, anchors),
    preserveReadOrder: state.preserveReadOrder,
  };
}

function getActiveVirtualPath(
  action: ReplayAction | null,
  virtualFileTree: VirtualFileTree,
  rawHighlights: HighlightState,
): string {
  const candidates = action ? collectVirtualPathsFromAction(action) : [];
  for (const id of getHighlightAnchorIds(rawHighlights)) {
    const path = getPathFromVirtualEvidenceId(id);
    if (path) {
      candidates.push(path);
    }
  }
  for (const path of candidates) {
    const knownPath = findKnownVirtualPath(virtualFileTree, path);
    if (knownPath && knownPath !== "/") {
      return knownPath;
    }
  }
  return "";
}

function getVirtualPathIds(virtualFileTree: VirtualFileTree, path: string): string[] {
  const knownPath = findKnownVirtualPath(virtualFileTree, path);
  if (!knownPath || knownPath === "/") {
    return [];
  }
  const result: string[] = [];
  let current = knownPath;
  while (current && current !== "/") {
    result.push(current);
    current = virtualFileTree.parentByPath.get(current) ?? "";
  }
  return result.reverse();
}

function collectVirtualPathsFromAction(action: ReplayAction): string[] {
  const args = readObject(action.args);
  const result = readObject(action.result);
  const resultField = readObject(result?.field);
  const paths = [
    readString(args?.path),
    readString(result?.path),
    readString(resultField?.path),
    ...collectVirtualEvidencePaths(args?.evidence),
    ...collectVirtualEvidencePaths(result?.evidence),
    ...collectVirtualEvidencePaths(args?.final_evidence),
    ...collectVirtualEvidencePaths(resultField?.evidence),
    ...readObjectArray(result?.evidence_texts).map((item) => readString(item.path)),
    ...readObjectArray(resultField?.evidence_texts).map((item) => readString(item.path)),
  ];
  return Array.from(new Set(paths.map(normalizeVirtualPath).filter(Boolean)));
}

function collectVirtualEvidencePaths(value: unknown): string[] {
  return readObjectArray(value)
    .map((selector) => readString(selector.path))
    .filter(Boolean);
}

function collectVirtualEvidenceTexts(action: ReplayAction): VirtualEvidenceText[] {
  const args = readObject(action.args);
  const result = readObject(action.result);
  const resultField = readObject(result?.field);
  const actionPath = readString(result?.path) || readString(args?.path) || readString(resultField?.path);
  const texts: VirtualEvidenceText[] = [];
  const addEvidenceTexts = (value: unknown) => {
    for (const item of readObjectArray(value)) {
      const path = readString(item.path) || actionPath;
      const selector = readString(item.selector) || readString(item.id);
      const text = readString(item.text) || readString(item.preview);
      if (path && selector && text) {
        texts.push({ path, selector, text });
      }
    }
  };
  addEvidenceTexts(result?.evidence_texts);
  addEvidenceTexts(resultField?.evidence_texts);
  if (getActionType(action) === "anchors" && actionPath) {
    for (const anchor of readObjectArray(result?.anchors)) {
      const selector = readString(anchor.id);
      const text = readString(anchor.preview);
      if (selector && text) {
        texts.push({ path: actionPath, selector, text });
      }
    }
  }
  return texts;
}

function getBindEvidenceInlineAnchors(actions: ReplayAction[]): InlineEvidenceAnchor[] {
  const anchors: InlineEvidenceAnchor[] = [];
  const seen = new Set<string>();
  for (const action of actions) {
    if (getActionType(action) !== "bind_evidence") {
      continue;
    }
    for (const item of collectVirtualEvidenceTexts(action)) {
      const normalizedPath = normalizeVirtualPath(item.path);
      if (!normalizedPath || !item.selector || !item.text) {
        continue;
      }
      const id = makeInlineEvidenceAnchorId(normalizedPath, item.selector);
      const key = `${id}\n${normalizeVirtualText(item.text)}`;
      if (seen.has(key)) {
        continue;
      }
      seen.add(key);
      anchors.push({
        path: normalizedPath,
        selector: item.selector,
        text: item.text,
        id,
        matched: false,
      });
    }
  }
  return anchors;
}

function parseVirtualTreePaths(text: string): string[] {
  if (!text) {
    return [];
  }
  const paths: string[] = [];
  const stack = ["/"];
  for (const line of text.split("\n")) {
    if (!line.trim()) {
      continue;
    }
    const trimmed = line.trim();
    if (trimmed === "/") {
      stack[0] = "/";
      continue;
    }
    if (trimmed.startsWith("/") && !trimmed.includes("──")) {
      paths.push(trimmed);
      continue;
    }
    const connectorMatch = line.match(/[├└]\s*──\s*(.+)$/);
    const labelWithSuffix = connectorMatch
      ? connectorMatch[1].trim()
      : formatVirtualTreeLineLabel(line);
    const label = labelWithSuffix.replace(/\/$/, "").trim();
    if (!label || label === "/") {
      continue;
    }
    const connectorIndex = connectorMatch?.index ?? 0;
    const depth = Math.max(1, Math.floor(connectorIndex / 4) + 1);
    const parent = stack[depth - 1] || "/";
    const path = normalizeVirtualPath(parent === "/" ? `/${label}` : `${parent}/${label}`);
    paths.push(path);
    stack[depth] = path;
    stack.length = depth + 1;
  }
  return Array.from(new Set(paths));
}

function inferVirtualFileKind(label: string): VirtualFileKind {
  return /\.[A-Za-z0-9_-]+$/.test(label) ? "file" : "folder";
}

function formatVirtualOutlineLabel(label: string, kind: VirtualFileKind): string {
  if (kind !== "file") {
    return label;
  }
  return label
    .replace(/\.(?:md|table|list)$/i, "")
    .replace(/^\d+-/, "")
    .trim() || label;
}

function normalizeVirtualPath(path: string): string {
  const rawPath = readString(path).split("#")[0]?.trim() ?? "";
  if (!rawPath) {
    return "";
  }
  const collapsed = rawPath.replace(/\\/g, "/").replace(/\/+/g, "/");
  const withRoot = collapsed.startsWith("/") ? collapsed : `/${collapsed}`;
  if (withRoot === "/") {
    return "/";
  }
  return withRoot.replace(/\/$/, "");
}

function makeVirtualEvidenceId(path: string, selector: string): string {
  const normalizedPath = normalizeVirtualPath(path);
  return normalizedPath && selector ? `${normalizedPath}#${selector}` : selector;
}

function makeInlineEvidenceAnchorId(path: string, selector: string): string {
  const normalizedPath = normalizeVirtualPath(path);
  const rawId = `inline-evidence-${normalizedPath}#${selector}`;
  return rawId.replace(/[^A-Za-z0-9_-]+/g, "-").replace(/^-+|-+$/g, "") || "inline-evidence";
}

function getPathFromVirtualEvidenceId(id: string): string {
  if (!id.startsWith("/")) {
    return "";
  }
  return normalizeVirtualPath(id.split("#")[0] ?? "");
}

function resolveVirtualEvidenceIds(ids: string[], anchors: VirtualHtmlAnchors): string[] {
  return Array.from(new Set(ids.map((id) => resolveVirtualEvidenceId(id, anchors)).filter(Boolean)));
}

function resolveVirtualEvidenceId(id: string, anchors: VirtualHtmlAnchors): string {
  if (!id) {
    return "";
  }
  const direct = anchors.byVirtualId.get(id);
  if (direct) {
    return direct;
  }
  const path = getPathFromVirtualEvidenceId(id);
  if (path) {
    const pathAnchor = anchors.byPath.get(path);
    if (pathAnchor) {
      return pathAnchor;
    }
  }
  const normalizedPath = normalizeVirtualPath(id);
  if (normalizedPath) {
    const pathAnchor = anchors.byPath.get(normalizedPath);
    if (pathAnchor) {
      return pathAnchor;
    }
  }
  const selectorAnchor = anchors.bySelector.get(id);
  return selectorAnchor || id;
}

function findKnownVirtualPath(virtualFileTree: VirtualFileTree, path: string): string {
  let current = normalizeVirtualPath(path);
  while (current) {
    if (virtualFileTree.byPath.has(current)) {
      return current;
    }
    if (current === "/") {
      return "";
    }
    current = normalizeVirtualPath(current.split("/").slice(0, -1).join("/") || "/");
  }
  return "";
}

function findMatchingHtmlElementId(elements: Array<{ id: string; text: string }>, text: string): string {
  const needle = normalizeVirtualText(text);
  if (!needle) {
    return "";
  }
  const exact = elements.find((element) => element.text === needle);
  if (exact) {
    return exact.id;
  }
  const match = elements
    .filter((element) => element.text.includes(needle) || needle.includes(element.text))
    .sort((left, right) => Math.abs(left.text.length - needle.length) - Math.abs(right.text.length - needle.length))[0];
  return match?.id ?? "";
}

function normalizeVirtualText(text: string): string {
  return text.replace(/\s+/g, " ").trim();
}

function reduceReplayFields(
  actions: ReplayAction[],
  finalFields: TaskResultField[],
  reviewFields: ReviewField[],
): ReplayField[] {
  const fields = new Map<string, ReplayField>();
  const reviewByName = new Map(reviewFields.map((field) => [field.field_name, field]));
  for (const field of finalFields) {
    const reviewField = reviewByName.get(field.field_name);
    const route = field.route ?? (reviewField?.needs_review ? "review" : null);
    fields.set(field.field_name, {
      sourceName: field.field_name,
      fieldName: field.display_name || reviewField?.display_name || field.field_name,
      fieldType: field.field_type ?? reviewField?.field_type ?? null,
      variants: field.variants ?? reviewField?.variants ?? [],
      status: "pending",
      value: field.agent_value ?? null,
      evidenceIds: [],
      route,
      routeReason: reviewField?.review_reason ?? null,
      needsReview: route === "review" && Boolean(reviewField?.needs_review),
      reviewField,
    });
  }
  for (const reviewField of reviewFields) {
    if (fields.has(reviewField.field_name)) {
      continue;
    }
    fields.set(reviewField.field_name, {
      sourceName: reviewField.field_name,
      fieldName: reviewField.display_name || reviewField.field_name,
      fieldType: reviewField.field_type ?? null,
      variants: reviewField.variants ?? [],
      status: reviewField.field_status || "failed",
      value: reviewField.agent_value,
      evidenceIds: [],
      route: reviewField.needs_review ? "review" : null,
      routeReason: reviewField.review_reason ?? null,
      needsReview: reviewField.needs_review,
      reviewField,
    });
  }
  for (const action of actions) {
    if (getActionType(action) !== "set_field" && getActionType(action) !== "write_field") {
      continue;
    }
    const payload = getSetFieldPayload(action);
    if (!payload.name) {
      continue;
    }
    const previous = fields.get(payload.name);
    const route = previous?.route ?? null;
    fields.set(payload.name, {
      sourceName: payload.name,
      fieldName: previous?.fieldName || payload.name,
      fieldType: previous?.fieldType ?? null,
      variants: previous?.variants ?? [],
      status: payload.status || "resolved",
      value: payload.value,
      evidenceIds: payload.evidenceIds,
      route,
      routeReason: previous?.routeReason ?? null,
      needsReview: route === "review" && Boolean(previous?.needsReview),
      reviewField: previous?.reviewField,
    });
  }
  return Array.from(fields.values());
}

function isFieldWriteActionType(actionType: string): boolean {
  return actionType === "set_field" || actionType === "write_field";
}

function formatVirtualTreeLineLabel(line: string): string {
  const trimmed = line.trim();
  if (trimmed === "/") {
    return "/";
  }
  return trimmed.replace(/^[│├└─\s]+/, "").replace(/\/$/, "");
}

function readEvidenceSelectorIds(value: unknown): string[] | null {
  const selectors = readObjectArray(value);
  if (selectors.length === 0) {
    return null;
  }
  const ids = selectors.flatMap((selector) => {
    const path = readString(selector.path);
    return ["sentences", "items", "rows"].flatMap((key) =>
      (readStringArray(selector[key]) ?? []).map((id) => (path ? makeVirtualEvidenceId(path, id) : id)),
    );
  });
  return ids.length > 0 ? Array.from(new Set(ids)) : null;
}

function getHighlightState(_actions: ReplayAction[], currentAction: ReplayAction | null): HighlightState {
  if (!currentAction) {
    return emptyHighlightState();
  }
  const type = getActionType(currentAction);
  if (type === "read_element" || type === "read_section") {
    return getReadActionHighlightState(currentAction);
  }
  if (type === "table_extraction") {
    return getTableExtractionHighlightState(currentAction);
  }
  if (type === "search_elements") {
    return getSearchElementsHighlightState(currentAction);
  }
  if (type === "paragraph_extraction") {
    return getParagraphExtractionHighlightState(currentAction);
  }
  if (isFieldWriteActionType(type)) {
    const payload = getSetFieldPayload(currentAction);
    return {
      ...emptyHighlightState(),
      currentIds: payload.evidenceIds,
      readIds: payload.evidenceIds,
    };
  }
  return getGenericEvidenceHighlightState(currentAction);
}

function emptyHighlightState(): HighlightState {
  return {
    currentIds: [],
    tableReferenceIds: [],
    tableRowIds: [],
    readIds: [],
    preserveReadOrder: false,
  };
}

function getReadActionHighlightState(action: ReplayAction): HighlightState {
  const args = readObject(action.args);
  const result = readObject(action.result);
  const elementId = readString(result?.id) || readString(result?.section_id) || readString(args?.element_id) || readString(args?.section_id);
  const html = readString(result?.html);
  const visibleIds = extractIdsFromToolHtml(html);
  if (readString(result?.type).toUpperCase() === "TABLE" || html.includes("<table-ref")) {
    return {
      ...emptyHighlightState(),
      tableReferenceIds: elementId ? [elementId] : visibleIds,
      readIds: elementId ? [elementId] : visibleIds,
      preserveReadOrder: true,
    };
  }
  const currentIds = visibleIds.length > 0 ? visibleIds : readStringArray(result?.evidence_ids) ?? [];
  return {
    ...emptyHighlightState(),
    currentIds,
    readIds: currentIds,
    preserveReadOrder: true,
  };
}

function getTableExtractionHighlightState(action: ReplayAction): HighlightState {
  const result = readObject(action.result);
  const rowIds = extractTableExtractionRowIds(result);
  if (rowIds.length === 0) {
    return emptyHighlightState();
  }
  return {
    ...emptyHighlightState(),
    tableRowIds: rowIds,
    readIds: rowIds,
    preserveReadOrder: true,
  };
}

function getParagraphExtractionHighlightState(action: ReplayAction): HighlightState {
  const args = readObject(action.args);
  const result = readObject(action.result);
  const matches = Array.isArray(result?.matches) ? result.matches : [];
  const ids = matches.flatMap((match) => readStringArray(readObject(match)?.evidence_ids) ?? []);
  const fallbackId = readString(result?.element_id) || readString(args?.element_id);
  const currentIds = Array.from(new Set((ids.length > 0 ? ids : [fallbackId]).filter(Boolean)));
  return {
    ...emptyHighlightState(),
    currentIds,
    readIds: currentIds,
    preserveReadOrder: true,
  };
}

function getSearchElementsHighlightState(action: ReplayAction): HighlightState {
  const result = readObject(action.result);
  const ids = readSearchElementMatches(result).flatMap((match) => match.evidenceIds);
  const currentIds = Array.from(new Set(ids.filter(Boolean)));
  if (currentIds.length === 0) {
    return emptyHighlightState();
  }
  return {
    ...emptyHighlightState(),
    currentIds,
    readIds: currentIds,
    preserveReadOrder: true,
  };
}

function getGenericEvidenceHighlightState(action: ReplayAction): HighlightState {
  const args = readObject(action.args);
  const result = readObject(action.result);
  const resultField = readObject(result?.field);
  const virtualEvidenceIds = Array.from(new Set([
    ...(readEvidenceSelectorIds(args?.evidence) ?? []),
    ...(readEvidenceSelectorIds(result?.evidence) ?? []),
    ...(readEvidenceSelectorIds(args?.final_evidence) ?? []),
    ...(readEvidenceSelectorIds(resultField?.evidence) ?? []),
    ...collectVirtualEvidenceTexts(action).map((item) => makeVirtualEvidenceId(item.path, item.selector)),
  ]));
  if (virtualEvidenceIds.length > 0) {
    return {
      ...emptyHighlightState(),
      currentIds: virtualEvidenceIds,
      readIds: virtualEvidenceIds,
      preserveReadOrder: true,
    };
  }
  const evidenceIds = readStringArray(result?.evidence_ids) ?? [];
  const actionPath = readString(result?.path) || readString(args?.path);
  const fallbackId =
    readString(args?.element_id) ||
    readString(args?.section_id) ||
    readString(args?.table_id) ||
    (actionPath ? normalizeVirtualPath(actionPath) : "");
  const currentIds = Array.from(new Set((evidenceIds.length > 0 ? evidenceIds : [fallbackId]).filter(Boolean)));
  if (currentIds.length === 0) {
    return emptyHighlightState();
  }
  return {
    ...emptyHighlightState(),
    currentIds,
    readIds: currentIds,
    preserveReadOrder: false,
  };
}

function extractTableExtractionRowIds(result: Record<string, unknown> | null): string[] {
  const rows = Array.isArray(result?.rows) ? result.rows : [];
  const ids: string[] = [];
  for (const row of rows) {
    const rowId = readString(readObject(row)?.row_id);
    if (rowId) {
      ids.push(rowId);
    }
  }
  return Array.from(new Set(ids));
}

function readSearchElementMatches(result: Record<string, unknown> | null): Array<{
  elementId: string;
  snippet: string;
  evidenceIds: string[];
}> {
  const matches = Array.isArray(result?.matches) ? result.matches : [];
  return matches
    .map((match) => {
      const item = readObject(match);
      const evidenceIds = readStringArray(item?.evidence_ids) ?? [];
      const elementId = readString(item?.element_id) || evidenceIds[0] || "";
      const snippet = readString(item?.snippet) || readString(item?.text) || "";
      return {
        elementId,
        snippet,
        evidenceIds: evidenceIds.length > 0 ? evidenceIds : elementId ? [elementId] : [],
      };
    })
    .filter((match) => match.elementId || match.snippet);
}

function extractIdsFromToolHtml(html: string): string[] {
  if (!html || typeof window === "undefined") {
    return [];
  }
  const parsed = new DOMParser().parseFromString(html, "text/html");
  return Array.from(parsed.body.querySelectorAll<HTMLElement>("[id]"))
    .map((element) => element.id)
    .filter(Boolean);
}

function getHighlightAnchorIds(state: HighlightState): string[] {
  if (state.readIds.length > 0) {
    return state.readIds;
  }
  if (state.currentIds.length > 0) {
    return state.currentIds;
  }
  if (state.tableReferenceIds.length > 0) {
    return state.tableReferenceIds;
  }
  return state.tableRowIds;
}

function getReplayNavigationKey(activeOutlineId: string, readableEvidenceIds: string[]): string {
  const evidenceKey = readableEvidenceIds[0] ?? "";
  if (!activeOutlineId && !evidenceKey) {
    return "";
  }
  return `${activeOutlineId}::${evidenceKey}`;
}

function getSetFieldPayload(action: ReplayAction): {
  name: string;
  value: unknown;
  evidenceIds: string[];
  status: string;
} {
  const resultField = readObject(readObject(action.result)?.field) as ReplayFieldState | null;
  const args = readObject(action.args);
  const name =
    readString(args?.name) ||
    readString(args?.field_id) ||
    readString(resultField?.name) ||
    readString(resultField?.field_name) ||
    readString((resultField as Record<string, unknown> | null)?.field_id);
  const selectorEvidenceIds =
    readEvidenceSelectorIds(args?.final_evidence) ||
    readEvidenceSelectorIds((resultField as Record<string, unknown> | null)?.evidence);
  const evidenceIds = readStringArray(args?.evidence_ids) || readStringArray(resultField?.evidence_ids) || selectorEvidenceIds || [];
  return {
    name,
    value: args && "value" in args ? args.value : resultField?.value,
    evidenceIds,
    status: readString(args?.status) || readString(resultField?.status) || "resolved",
  };
}

function getActionTarget(action: ReplayAction): string {
  const args = readObject(action.args);
  return (
    readString(args?.path) ||
    readString(args?.section_id) ||
    readString(args?.element_id) ||
    readString(args?.table_id) ||
    readString(args?.name)
  );
}

function getActionReason(action: ReplayAction): string {
  return readString(action.reason);
}

function getActionType(action: ReplayAction): string {
  return action.tool_name || action.action_type || "";
}

function applyHighlights(iframe: HTMLIFrameElement | null, state: HighlightState, isFieldWrite = false) {
  const document = iframe?.contentDocument;
  if (!document) {
    return;
  }
  document.querySelectorAll(".is-current-highlight").forEach((element) => {
    element.classList.remove("is-current-highlight");
  });
  document.querySelectorAll(".is-field-write-highlight").forEach((element) => {
    element.classList.remove("is-field-write-highlight");
  });
  document.querySelectorAll(".is-committed-evidence").forEach((element) => {
    element.classList.remove("is-committed-evidence");
  });
  document.querySelectorAll(".is-table-row-result-highlight").forEach((element) => {
    element.classList.remove("is-table-row-result-highlight");
  });
  document.querySelectorAll(".is-table-reference-highlight").forEach((element) => {
    element.classList.remove("is-table-reference-highlight");
  });
  for (const id of state.currentIds) {
    const element = document.getElementById(id);
    const tableAnchors = getWholeTableEvidenceAnchors(document, id);
    if (tableAnchors.length > 0) {
      for (const anchor of tableAnchors) {
        anchor.classList.add("is-current-highlight");
        if (isFieldWrite) {
          anchor.classList.add("is-field-write-highlight");
        }
      }
      continue;
    }
    element?.classList.add("is-current-highlight");
    if (isFieldWrite) {
      element?.classList.add("is-field-write-highlight");
    }
  }
  for (const id of state.tableReferenceIds) {
    highlightTableReference(document, id);
  }
  for (const id of state.tableRowIds) {
    document.getElementById(id)?.classList.add("is-table-row-result-highlight");
  }
}

function highlightTableReference(document: Document, tableId: string) {
  for (const anchor of getWholeTableEvidenceAnchors(document, tableId)) {
    anchor.classList.add("is-table-reference-highlight");
  }
}

function ensureTableReferenceReadAnchor(document: Document, tableId: string) {
  return getWholeTableEvidenceAnchors(document, tableId)[0] ?? null;
}

function ensureElementId(document: Document, element: HTMLElement, preferredId: string) {
  if (element.id) {
    return;
  }
  let candidate = preferredId;
  let suffix = 2;
  while (document.getElementById(candidate)) {
    candidate = `${preferredId}-${suffix}`;
    suffix += 1;
  }
  element.id = candidate;
}

function getWholeTableEvidenceAnchors(document: Document, tableId: string): HTMLElement[] {
  const element = document.getElementById(tableId);
  if (!element || !isWholeTableEvidenceElement(element)) {
    return [];
  }
  const anchors: HTMLElement[] = [];
  const caption = getTableCaptionElement(element);
  if (caption) {
    ensureElementId(document, caption, getTableCaptionAnchorId(tableId));
    caption.setAttribute("data-table-evidence-anchor", "true");
    anchors.push(caption);
  }
  const header = getTableHeaderRowElement(element);
  if (header) {
    ensureElementId(document, header, getTableHeaderAnchorId(tableId));
    header.setAttribute("data-table-evidence-anchor", "true");
    anchors.push(header);
  }
  return anchors;
}

function getWholeTableEvidenceReadAnchorId(document: Document, tableId: string): string | null {
  return getWholeTableEvidenceAnchors(document, tableId)[0]?.id ?? null;
}

function getScrollTargetElement(document: Document, evidenceId: string): HTMLElement | null {
  return getWholeTableEvidenceAnchors(document, evidenceId)[0] ?? document.getElementById(evidenceId);
}

function getScrollBlock(element: HTMLElement | null): ScrollLogicalPosition {
  if (!element) {
    return "center";
  }
  return isTableEvidenceAnchor(element) ? "start" : "center";
}

function isTableEvidenceAnchor(element: HTMLElement): boolean {
  return element.getAttribute("data-table-evidence-anchor") === "true";
}

function isWholeTableEvidenceElement(element: HTMLElement): boolean {
  const tagName = element.tagName.toLowerCase();
  const dataType = (element.getAttribute("data-type") || "").toLowerCase();
  const className = element.getAttribute("class") || "";
  return tagName === "table" || dataType.includes("table") || className.includes("block-table") || Boolean(element.querySelector("table"));
}

function getTableCaptionElement(element: Element): HTMLElement | null {
  return element.querySelector<HTMLElement>(".caption, figcaption, caption");
}

function getTableHeaderRowElement(element: Element): HTMLElement | null {
  if (element.tagName.toLowerCase() === "tr") {
    return element as HTMLElement;
  }
  const table = element.tagName.toLowerCase() === "table" ? element : element.querySelector("table");
  return table?.querySelector<HTMLElement>("thead tr, tr") ?? null;
}

function getTableCaptionAnchorId(tableId: string) {
  return `table-caption-anchor-${tableId}`;
}

function getTableHeaderAnchorId(tableId: string) {
  return `table-header-anchor-${tableId}`;
}

function scrollToEvidence(iframe: HTMLIFrameElement | null, evidenceId: string) {
  const document = iframe?.contentDocument;
  const element = document ? getScrollTargetElement(document, evidenceId) : null;
  if (typeof element?.scrollIntoView === "function") {
    element.scrollIntoView({ behavior: "smooth", block: getScrollBlock(element) });
  }
}

function scrollOutlineItemIntoView(container: HTMLDivElement | null, item: HTMLButtonElement | null) {
  if (!container || !item) {
    return;
  }
  const containerRect = container.getBoundingClientRect();
  const itemRect = item.getBoundingClientRect();
  const nextTop = container.scrollTop + itemRect.top - containerRect.top - container.clientHeight * 0.35;
  const top = Math.max(0, nextTop);
  if (typeof container.scrollTo === "function") {
    container.scrollTo({ top, behavior: "smooth" });
    return;
  }
  container.scrollTop = top;
}

function getElementPointInContainer(container: HTMLElement | null, element: HTMLElement | null) {
  if (!container || !element) {
    return null;
  }
  const containerRect = container.getBoundingClientRect();
  const elementRect = element.getBoundingClientRect();
  return {
    x: elementRect.left - containerRect.left + Math.min(92, elementRect.width * 0.42),
    y: elementRect.top - containerRect.top + elementRect.height / 2,
  };
}

function getReadableEvidenceIds(
  iframe: HTMLIFrameElement | null,
  ids: string[],
  options?: { preserveOrder?: boolean; documentOrder?: boolean; fieldWrite?: boolean },
): string[] {
  const iframeDocument = iframe?.contentDocument;
  if (!iframeDocument) {
    return ids;
  }
  const seen = new Set<string>();
  const readable: string[] = [];
  const fallback: string[] = [];
  for (const id of ids) {
    const resolvedId = options?.fieldWrite ? getWholeTableEvidenceReadAnchorId(iframeDocument, id) ?? id : id;
    const element = iframeDocument.getElementById(resolvedId);
    if (!element || seen.has(resolvedId)) {
      continue;
    }
    seen.add(resolvedId);
    const expanded = expandReadableDescendantIds(element);
    if (expanded.length > 0) {
      for (const expandedId of expanded) {
        if (!seen.has(expandedId)) {
          seen.add(expandedId);
          readable.push(expandedId);
        }
      }
      continue;
    }
    if (isCoarseNavigationElement(element)) {
      fallback.push(resolvedId);
    } else {
      readable.push(resolvedId);
    }
  }
  const candidates = readable.length > 0 ? readable : fallback;
  if (options?.documentOrder) {
    return sortEvidenceIdsByDocumentOrder(iframe, candidates);
  }
  if (options?.preserveOrder) {
    return candidates;
  }
  return sortEvidenceIdsByViewportDistance(iframe, candidates);
}

function getReadableEvidenceIdsForHighlightState(
  iframe: HTMLIFrameElement | null,
  state: HighlightState,
  fallbackIds: string[],
  options?: { preserveOrder?: boolean; documentOrder?: boolean; fieldWrite?: boolean },
): string[] {
  const iframeDocument = iframe?.contentDocument;
  if (!iframeDocument || state.tableReferenceIds.length === 0) {
    return getReadableEvidenceIds(iframe, fallbackIds, options);
  }
  const ids = state.tableReferenceIds.flatMap((tableId) => {
    const anchor = ensureTableReferenceReadAnchor(iframeDocument, tableId);
    return anchor?.id ? [anchor.id] : [];
  });
  return getReadableEvidenceIds(iframe, ids.length > 0 ? ids : fallbackIds, options);
}

function sortEvidenceIdsByDocumentOrder(iframe: HTMLIFrameElement | null, ids: string[]): string[] {
  const iframeDocument = iframe?.contentDocument;
  if (!iframeDocument || ids.length <= 1) {
    return ids;
  }
  const indexById = new Map<string, number>();
  Array.from(iframeDocument.body.querySelectorAll<HTMLElement>("[id]")).forEach((element, index) => {
    indexById.set(element.id, index);
  });
  return [...ids].sort(
    (a, b) =>
      (indexById.get(a) ?? Number.MAX_SAFE_INTEGER) -
      (indexById.get(b) ?? Number.MAX_SAFE_INTEGER),
  );
}

function sortEvidenceIdsByViewportDistance(iframe: HTMLIFrameElement | null, ids: string[]): string[] {
  const iframeWindow = iframe?.contentWindow;
  const iframeDocument = iframe?.contentDocument;
  if (!iframeWindow || !iframeDocument || ids.length <= 1) {
    return ids;
  }
  const viewportCenter = iframeWindow.scrollY + iframeWindow.innerHeight / 2;
  return [...ids]
    .map((id, index) => {
      const element = iframeDocument.getElementById(id);
      if (!element) {
        return { id, index, distance: Number.POSITIVE_INFINITY };
      }
      const rect = element.getBoundingClientRect();
      const elementCenter = iframeWindow.scrollY + rect.top + rect.height / 2;
      return {
        id,
        index,
        distance: Math.abs(elementCenter - viewportCenter),
      };
    })
    .sort((a, b) => (a.distance === b.distance ? a.index - b.index : a.distance - b.distance))
    .map((item) => item.id);
}

function getEvidenceReadMode(iframe: HTMLIFrameElement | null, evidenceId: string): EvidenceReadMode {
  const element = iframe?.contentDocument?.getElementById(evidenceId);
  if (!element) {
    return "line";
  }
  const tagName = element.tagName.toLowerCase();
  const dataType = (element.getAttribute("data-type") || "").toLowerCase();
  const className = element.getAttribute("class") || "";
  const isTable =
    tagName === "table" ||
    tagName === "tr" ||
    tagName === "td" ||
    tagName === "th" ||
    dataType.includes("table") ||
    className.includes("table") ||
    Boolean(element.querySelector("table"));
  const isList =
    tagName === "ul" ||
    tagName === "ol" ||
    tagName === "li" ||
    dataType.includes("list") ||
    className.includes("list");
  return isTable || isList ? "block" : "line";
}

function getEvidenceBlockReadDuration(iframe: HTMLIFrameElement | null, evidenceId: string): number {
  const element = iframe?.contentDocument?.getElementById(evidenceId);
  if (!element) {
    return 900;
  }
  const textLength = (element.textContent || "").replace(/\s+/g, "").length;
  const rowCount = element.querySelectorAll("tr, li").length;
  return Math.max(900, Math.min(4200, 700 + textLength * 8 + rowCount * 120));
}

function highlightEvidenceBlock(iframe: HTMLIFrameElement | null, evidenceId: string) {
  const iframeDocument = iframe?.contentDocument;
  const element = iframeDocument?.getElementById(evidenceId);
  if (!element) {
    return;
  }
  clearReadingLineHighlight(iframe);
  element.classList.add("is-reading-line");
}

function expandReadableDescendantIds(element: HTMLElement): string[] {
  if (!isCoarseNavigationElement(element)) {
    return [];
  }
  const descendants = Array.from(
    element.querySelectorAll<HTMLElement>(
      [
        "figure[id]",
        "table[id]",
        "tr[id]",
        "p[id]",
        "li[id]",
        ".block-table[id]",
        ".block-text[id]",
        ".block-list[id]",
        ".block-list-item[id]",
        "[data-type='table'][id]",
        "[data-type='paragraph'][id]",
        "[data-type='text'][id]",
        "[data-type='list_item'][id]",
        "[data-type='list-item'][id]",
      ].join(","),
    ),
  );
  return descendants
    .filter((descendant) => !isCoarseNavigationElement(descendant))
    .map((descendant) => descendant.id)
    .filter(Boolean)
    .slice(0, 24);
}

function isCoarseNavigationElement(element: Element): boolean {
  const tagName = element.tagName.toLowerCase();
  const dataType = (element.getAttribute("data-type") || "").toLowerCase();
  const className = element.getAttribute("class") || "";
  return (
    /^h[1-6]$/.test(tagName) ||
    tagName === "section" ||
    dataType.includes("title") ||
    dataType.includes("section") ||
    className.includes("section") ||
    className.includes("title")
  );
}

function getEvidenceReadingLines(iframe: HTMLIFrameElement | null, evidenceId?: string): ReadingLine[] {
  const iframeWindow = iframe?.contentWindow;
  const iframeDocument = iframe?.contentDocument;
  if (!iframeWindow || !iframeDocument || !evidenceId) {
    return [];
  }
  const element = iframeDocument.getElementById(evidenceId);
  if (!element) {
    return [];
  }

  const wrappedLines = getWrappedTextLineBoxes(iframeDocument, iframeWindow, evidenceId);
  if (wrappedLines.length > 0) {
    return wrappedLines.slice(0, 160);
  }

  const range = iframeDocument.createRange();
  range.selectNodeContents(element);
  const rawRects = typeof range.getClientRects === "function"
    ? Array.from(range.getClientRects())
    .filter((rect) => rect.width > 8 && rect.height > 4)
    .map((rect) => ({
      left: rect.left + iframeWindow.scrollX,
      right: rect.right + iframeWindow.scrollX,
      top: rect.top + iframeWindow.scrollY,
      bottom: rect.bottom + iframeWindow.scrollY,
    }))
    : [];
  range.detach();

  if (rawRects.length === 0) {
    const rect = element.getBoundingClientRect();
    return [
      {
        left: rect.left + iframeWindow.scrollX,
        right: rect.right + iframeWindow.scrollX,
        top: rect.top + iframeWindow.scrollY,
        bottom: rect.bottom + iframeWindow.scrollY,
        spanIndexes: [],
      },
    ];
  }

  return mergeTextLineBoxes(rawRects.map((rect) => ({ ...rect, spanIndexes: [] }))).slice(0, 160);
}

function getWrappedTextLineBoxes(
  iframeDocument: Document,
  iframeWindow: Window,
  evidenceId: string,
): ReadingLine[] {
  const spans = Array.from(
    iframeDocument.querySelectorAll<HTMLElement>(`[data-reading-line-for="${cssEscape(evidenceId)}"]`),
  );
  const rects = spans.flatMap((span, spanIndex) =>
    Array.from(span.getClientRects())
      .filter((rect) => rect.width > 1 && rect.height > 4)
      .map((rect) => ({
        left: rect.left + iframeWindow.scrollX,
        right: rect.right + iframeWindow.scrollX,
        top: rect.top + iframeWindow.scrollY,
        bottom: rect.bottom + iframeWindow.scrollY,
        spanIndexes: [spanIndex],
      })),
  );
  return mergeTextLineBoxes(rects);
}

function highlightEvidenceTextLine(
  iframe: HTMLIFrameElement | null,
  evidenceId: string | undefined,
  line: ReadingLine,
) {
  const iframeDocument = iframe?.contentDocument;
  if (!iframeDocument || !evidenceId) {
    return;
  }
  clearReadingLineHighlight(iframe);
  const lines = iframeDocument.querySelectorAll(`[data-reading-line-for="${cssEscape(evidenceId)}"]`);
  for (const spanIndex of line.spanIndexes) {
    lines.item(spanIndex)?.classList.add("is-reading-line");
  }
}

function clearReadingLineHighlight(iframe: HTMLIFrameElement | null) {
  const iframeDocument = iframe?.contentDocument;
  if (!iframeDocument) {
    return;
  }
  iframeDocument.querySelectorAll(".is-reading-line").forEach((element) => {
    element.classList.remove("is-reading-line");
  });
}

function mergeTextLineBoxes(rects: ReadingLine[]): ReadingLine[] {
  const sorted = [...rects].sort((a, b) => (Math.abs(a.top - b.top) > 4 ? a.top - b.top : a.left - b.left));
  const lines: ReadingLine[] = [];
  for (const rect of sorted) {
    const previous = lines[lines.length - 1];
    if (previous && Math.abs(previous.top - rect.top) <= 5) {
      previous.left = Math.min(previous.left, rect.left);
      previous.right = Math.max(previous.right, rect.right);
      previous.top = Math.min(previous.top, rect.top);
      previous.bottom = Math.max(previous.bottom, rect.bottom);
      previous.spanIndexes.push(...rect.spanIndexes);
    } else {
      lines.push({ ...rect });
    }
  }
  return lines.filter((line) => line.right - line.left > 10);
}

function ensureTextLineVisible(iframe: HTMLIFrameElement | null, line: TextLineBox) {
  const iframeWindow = iframe?.contentWindow;
  if (!iframeWindow) {
    return;
  }
  const viewportTop = iframeWindow.scrollY;
  const viewportBottom = viewportTop + iframeWindow.innerHeight;
  if (
    (line.top < viewportTop + 72 || line.bottom > viewportBottom - 72) &&
    typeof iframeWindow.scrollTo === "function" &&
    !isJsdomWindow(iframeWindow)
  ) {
    try {
      iframeWindow.scrollTo({
        top: Math.max(0, line.top - iframeWindow.innerHeight * 0.36),
        behavior: "smooth",
      });
    } catch {
      // jsdom 暂不实现 iframe window.scrollTo；真实浏览器会正常滚动。
    }
  }
}

function isJsdomWindow(iframeWindow: Window): boolean {
  return iframeWindow.navigator.userAgent.toLowerCase().includes("jsdom");
}

function getTextLinePointInContainer(
  container: HTMLElement | null,
  iframe: HTMLIFrameElement | null,
  line: TextLineBox,
  pointIndex: number,
) {
  const iframeWindow = iframe?.contentWindow;
  if (!container || !iframe || !iframeWindow) {
    return null;
  }
  const containerRect = container.getBoundingClientRect();
  const iframeRect = iframe.getBoundingClientRect();
  const xRatio = pointIndex === 0 ? 0.02 : 0.98;
  const viewportLeft = line.left - iframeWindow.scrollX;
  const viewportRight = line.right - iframeWindow.scrollX;
  const viewportBottom = line.bottom - iframeWindow.scrollY;
  return {
    x: iframeRect.left - containerRect.left + viewportLeft + (viewportRight - viewportLeft) * xRatio,
    y: iframeRect.top - containerRect.top + viewportBottom + 8,
  };
}

function cssEscape(value: string) {
  if (typeof CSS !== "undefined" && typeof CSS.escape === "function") {
    return CSS.escape(value);
  }
  return value.replace(/["\\]/g, "\\$&");
}

function buildReplayHtml(displayHtml: string, inlineAnchors: InlineEvidenceAnchor[] = []): string {
  const bodyHtml = sanitizeReplayDisplayHtml(applyInlineEvidenceAnchors(displayHtml, inlineAnchors));
  return `<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<style>
html { scroll-behavior: smooth; }
body {
  margin: 0;
  min-height: 100vh;
  box-sizing: border-box;
  padding: clamp(22px, 3.2vw, 40px);
  background: #edf2f7;
  color: #1f2937;
  font-family: ui-serif, Georgia, Cambria, "Times New Roman", Times, serif;
  font-size: 15px;
  line-height: 1.72;
  text-rendering: optimizeLegibility;
}
.document-canvas {
  max-width: min(100%, 920px);
  margin: 0 auto;
  box-sizing: border-box;
  min-height: calc(100vh - clamp(44px, 6.4vw, 80px));
  border: 1px solid #cbd5e1;
  border-top: 4px solid #94a3b8;
  background: #fff;
  padding: clamp(34px, 4.8vw, 64px);
  box-shadow: 0 26px 70px rgba(15, 23, 42, 0.18);
}
.document-canvas > :first-child {
  margin-top: 0;
}
.document-canvas h1,
.document-canvas h2,
.document-canvas h3,
.document-canvas h4 {
  color: #111827;
  font-family: ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  font-weight: 680;
  letter-spacing: 0;
  line-height: 1.24;
}
.document-canvas h1 {
  margin: 0 0 1.1rem;
  padding-bottom: 0.65rem;
  border-bottom: 1px solid #d9e1e7;
  font-size: 1.55rem;
}
.document-canvas h2 {
  margin: 2.1rem 0 0.8rem;
  font-size: 1.18rem;
}
.document-canvas h3 {
  margin: 1.6rem 0 0.55rem;
  font-size: 1.02rem;
}
.document-canvas p {
  margin: 0.72rem 0;
}
.document-canvas ul,
.document-canvas ol {
  margin: 0.72rem 0 0.95rem;
  padding-left: 1.35rem;
}
.document-canvas li {
  margin: 0.28rem 0;
  padding-left: 0.1rem;
}
.document-canvas figure {
  margin: 1.35rem 0;
  max-width: 100%;
  overflow-x: auto;
}
.document-canvas figcaption,
.document-canvas caption,
.document-canvas .caption {
  margin-bottom: 0.45rem;
  color: #4b5563;
  font-family: ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  font-size: 0.82rem;
  font-weight: 620;
  text-align: left;
}
.document-canvas table {
  width: max-content;
  min-width: min(100%, 38rem);
  border-collapse: collapse;
  border-top: 1px solid #9aa8b3;
  border-bottom: 1px solid #c8d2dc;
  font-family: ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  font-size: 0.86rem;
  line-height: 1.45;
}
.document-canvas th,
.document-canvas td {
  border: 0;
  border-bottom: 1px solid #e1e7ec;
  padding: 0.46rem 0.7rem;
  vertical-align: top;
  text-align: left;
}
.document-canvas th {
  background: #f7fafc;
  color: #111827;
  font-weight: 650;
}
.document-canvas tbody tr:hover > td,
.document-canvas tbody tr:hover > th {
  background: #f8fbfb;
}
.document-canvas blockquote {
  margin: 1rem 0;
  border-left: 3px solid #c8d2dc;
  padding-left: 0.9rem;
  color: #4b5563;
}
.reading-line {
  border-radius: 3px;
  transition: background 180ms ease, box-shadow 180ms ease;
}
.is-reading-line {
  background: rgba(14, 165, 164, 0.24);
  box-shadow: inset 0 -0.42em 0 rgba(14, 165, 164, 0.24);
}
.is-current-highlight {
  outline: 2px solid rgba(14, 165, 164, 0.58) !important;
  background: rgba(14, 165, 164, 0.1) !important;
  outline-offset: 2px;
  transition: background 180ms ease, outline-color 180ms ease, box-shadow 180ms ease;
}
.replay-inline-evidence.is-current-highlight {
  border-radius: 3px;
  outline: none !important;
  background: rgba(14, 165, 164, 0.12) !important;
  box-shadow: inset 0 -0.38em 0 rgba(14, 165, 164, 0.28), 0 0 0 1px rgba(14, 165, 164, 0.2);
}
.is-field-write-highlight {
  outline: 4px solid #0ea5a4 !important;
  background: rgba(14, 165, 164, 0.2) !important;
  animation: fieldWriteFlash 1.4s ease-out;
}
tr.is-current-highlight {
  outline-offset: -2px !important;
  box-shadow: inset 5px 0 0 #0ea5a4, 0 0 0 2px rgba(14, 165, 164, 0.18);
}
tr.is-current-highlight > td,
tr.is-current-highlight > th {
  background: rgba(14, 165, 164, 0.18) !important;
}
.is-table-row-result-highlight > td,
.is-table-row-result-highlight > th {
  background: rgba(14, 165, 164, 0.2) !important;
  box-shadow: inset 0 0 0 1px rgba(14, 165, 164, 0.28);
  transition: background 180ms ease, box-shadow 180ms ease;
}
.is-table-reference-highlight {
  display: inline-block;
  border-radius: 4px;
  background: rgba(14, 165, 164, 0.16) !important;
  box-shadow: 0 0 0 2px rgba(14, 165, 164, 0.34);
  transition: background 180ms ease, box-shadow 180ms ease;
}
tr.is-table-reference-highlight {
  display: table-row;
}
tr.is-table-reference-highlight > td,
tr.is-table-reference-highlight > th {
  background: rgba(14, 165, 164, 0.16) !important;
  box-shadow: inset 0 0 0 1px rgba(14, 165, 164, 0.26);
}
@keyframes fieldWriteFlash {
  0% { box-shadow: 0 0 0 0 rgba(14, 165, 164, 0.55); transform: scale(1); }
  28% { box-shadow: 0 0 0 12px rgba(14, 165, 164, 0.16); transform: scale(1.01); }
  100% { box-shadow: 0 0 0 0 rgba(14, 165, 164, 0); transform: scale(1); }
}
</style>
<script>
window.addEventListener("DOMContentLoaded", function () {
  function escapeAttr(value) {
    return String(value).replace(/"/g, "&quot;");
  }
  function wrapTextNode(node, ownerId) {
    var text = node.nodeValue || "";
    if (!text.trim()) return;
    var parts = text.split(/(\\s+)/);
    var fragment = document.createDocumentFragment();
    parts.forEach(function (part) {
      if (!part) return;
      if (/^\\s+$/.test(part)) {
        fragment.appendChild(document.createTextNode(part));
        return;
      }
      var span = document.createElement("span");
      span.className = "reading-line";
      span.setAttribute("data-reading-line-for", escapeAttr(ownerId));
      span.textContent = part;
      fragment.appendChild(span);
    });
    node.parentNode.replaceChild(fragment, node);
  }
  var nodes = [];
  var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
    acceptNode: function (node) {
      if (!node.nodeValue || !node.nodeValue.trim()) return NodeFilter.FILTER_REJECT;
      if (!node.parentElement) return NodeFilter.FILTER_REJECT;
      if (node.parentElement.closest("script, style, .reading-line")) return NodeFilter.FILTER_REJECT;
      if (!node.parentElement.closest("[id]")) return NodeFilter.FILTER_REJECT;
      return NodeFilter.FILTER_ACCEPT;
    }
  });
  while (walker.nextNode()) nodes.push(walker.currentNode);
  nodes.forEach(function (node) {
    var owner = node.parentElement && node.parentElement.closest("[id]");
    if (owner && owner.id) wrapTextNode(node, owner.id);
  });
});
</script>
</head>
<body data-document-canvas="true"><main class="document-canvas">${bodyHtml}</main></body>
</html>`;
}

function sanitizeReplayDisplayHtml(displayHtml: string): string {
  if (!displayHtml.trim() || typeof window === "undefined") {
    return displayHtml;
  }
  const document = new DOMParser().parseFromString(displayHtml, "text/html");
  document.body.querySelectorAll<HTMLElement>("[data-type], .page-number, .block-page_footer, .block-page_header").forEach((element) => {
    const text = normalizeOutlineText(element.textContent || "");
    if (isDocumentChromeElement(element, text)) {
      element.remove();
    }
  });
  return document.body.innerHTML;
}

function applyInlineEvidenceAnchors(displayHtml: string, inlineAnchors: InlineEvidenceAnchor[]): string {
  if (!displayHtml.trim() || inlineAnchors.length === 0 || typeof window === "undefined") {
    return displayHtml;
  }
  const document = new DOMParser().parseFromString(displayHtml, "text/html");
  for (const anchor of inlineAnchors) {
    anchor.matched = wrapFirstInlineEvidenceMatch(document, anchor);
  }
  return document.body.innerHTML;
}

function wrapFirstInlineEvidenceMatch(document: Document, anchor: InlineEvidenceAnchor): boolean {
  if (document.getElementById(anchor.id)) {
    return true;
  }
  const text = normalizeVirtualText(anchor.text);
  if (!text) {
    return false;
  }
  const candidates = Array.from(document.body.querySelectorAll<HTMLElement>("[id]"))
    .filter((element) => !isWholeTableEvidenceElement(element))
    .map((element) => ({
      element,
      text: normalizeVirtualText(element.textContent || ""),
    }))
    .filter((candidate) => candidate.text.includes(text))
    .sort((left, right) => left.text.length - right.text.length);
  for (const candidate of candidates) {
    if (wrapTextInElement(candidate.element, anchor.id, text)) {
      return true;
    }
  }
  return false;
}

function wrapTextInElement(element: HTMLElement, anchorId: string, text: string): boolean {
  const ownerDocument = element.ownerDocument;
  const walker = ownerDocument.createTreeWalker(element, NodeFilter.SHOW_TEXT, {
    acceptNode: (node) => {
      if (!node.nodeValue || !node.nodeValue.trim()) {
        return NodeFilter.FILTER_REJECT;
      }
      if (!node.parentElement || node.parentElement.closest("script, style, .replay-inline-evidence")) {
        return NodeFilter.FILTER_REJECT;
      }
      return NodeFilter.FILTER_ACCEPT;
    },
  });
  const textNodes: Text[] = [];
  while (walker.nextNode()) {
    textNodes.push(walker.currentNode as Text);
  }
  const match = findNormalizedTextRange(textNodes, text);
  if (!match) {
    return false;
  }
  const range = ownerDocument.createRange();
  range.setStart(match.start.node, match.start.offset);
  range.setEnd(match.end.node, match.end.offset);
  const span = ownerDocument.createElement("span");
  span.id = anchorId;
  span.className = "replay-inline-evidence";
  try {
    range.surroundContents(span);
  } catch {
    span.appendChild(range.extractContents());
    range.insertNode(span);
  }
  return true;
}

function findNormalizedTextRange(
  textNodes: Text[],
  needle: string,
): { start: { node: Text; offset: number }; end: { node: Text; offset: number } } | null {
  const normalizedNeedle = normalizeVirtualText(needle);
  if (!normalizedNeedle) {
    return null;
  }
  let normalizedText = "";
  const positions: Array<{ node: Text; offset: number }> = [];
  let previousWasSpace = false;
  for (const node of textNodes) {
    const rawText = node.nodeValue || "";
    for (let offset = 0; offset < rawText.length; offset += 1) {
      const char = rawText[offset] ?? "";
      if (/\s/.test(char)) {
        if (!previousWasSpace && normalizedText.length > 0) {
          normalizedText += " ";
          positions.push({ node, offset });
          previousWasSpace = true;
        }
        continue;
      }
      normalizedText += char;
      positions.push({ node, offset });
      previousWasSpace = false;
    }
  }
  const startIndex = normalizedText.indexOf(normalizedNeedle);
  if (startIndex < 0) {
    return null;
  }
  const endIndex = startIndex + normalizedNeedle.length - 1;
  const start = positions[startIndex];
  const end = positions[endIndex];
  if (!start || !end) {
    return null;
  }
  return {
    start,
    end: {
      node: end.node,
      offset: end.offset + 1,
    },
  };
}

function buildDocumentOutline(displayHtml: string, outlineTree: ReplayOutlineNode[]): DocumentOutline {
  const parsedDocument =
    displayHtml.trim() && typeof window !== "undefined"
      ? new DOMParser().parseFromString(displayHtml, "text/html")
      : null;
  if (outlineTree.length > 0) {
    return buildDocumentOutlineFromBackendTree(outlineTree, parsedDocument);
  }
  if (!parsedDocument) {
    return {
      items: [],
      tree: [],
      byElementId: new Map(),
      parentById: new Map(),
      labelByElementId: new Map(),
    };
  }
  const document = parsedDocument;
  const headingElements = Array.from(document.querySelectorAll("h1, h2, h3, h4, h5, h6"));
  const items = headingElements
    .map((element) => {
      const id = element.id;
      const label = formatHeaderLabel(normalizeOutlineText(element.textContent || ""));
      const level = Number(element.tagName.slice(1));
      return id && label ? { id, label, level } : null;
    })
    .filter((item): item is DocumentOutlineItem => item !== null);
  const tree: DocumentOutlineNode[] = [];
  const parentById = new Map<string, string>();
  const stack: DocumentOutlineNode[] = [];
  for (const item of items) {
    const node: DocumentOutlineNode = { ...item, children: [] };
    while (stack.length > 0 && stack[stack.length - 1].level >= node.level) {
      stack.pop();
    }
    const parent = stack[stack.length - 1];
    if (parent) {
      parent.children.push(node);
      parentById.set(node.id, parent.id);
    } else {
      tree.push(node);
    }
    stack.push(node);
  }
  const byElementId = new Map<string, string>();
  const labelByElementId = new Map<string, string>();
  let currentOutlineId = "";
  let currentHeaderText = "";
  for (const element of Array.from(document.body.querySelectorAll<HTMLElement>("[id]"))) {
    if (/^H[1-6]$/.test(element.tagName)) {
      currentOutlineId = element.id;
      currentHeaderText = normalizeOutlineText(element.textContent || "");
    }
    if (currentOutlineId) {
      byElementId.set(element.id, currentOutlineId);
    }
    labelByElementId.set(element.id, buildElementDisplayLabel(element, currentHeaderText));
  }
  return { items, tree, byElementId, parentById, labelByElementId };
}

function buildDocumentOutlineFromBackendTree(
  outlineTree: ReplayOutlineNode[],
  document: Document | null,
): DocumentOutline {
  const items: DocumentOutlineItem[] = [];
  const parentById = new Map<string, string>();
  const byElementId = new Map<string, string>();
  const labelByElementId = new Map<string, string>();
  const tree = normalizeBackendOutlineNodes(outlineTree, {
    parentId: "",
    level: 1,
    currentOutlineId: "",
    currentHeaderText: "",
    items,
    parentById,
    byElementId,
    labelByElementId,
  });
  if (document) {
    enrichElementLabelsFromHtml(document, { items, byElementId, labelByElementId });
  }
  return { items, tree, byElementId, parentById, labelByElementId };
}

function normalizeBackendOutlineNodes(
  nodes: ReplayOutlineNode[],
  context: {
    parentId: string;
    level: number;
    currentOutlineId: string;
    currentHeaderText: string;
    items: DocumentOutlineItem[];
    parentById: Map<string, string>;
    byElementId: Map<string, string>;
    labelByElementId: Map<string, string>;
  },
): DocumentOutlineNode[] {
  const result: DocumentOutlineNode[] = [];
  for (const rawNode of nodes) {
    const id = typeof rawNode.id === "string" ? rawNode.id : "";
    if (!id) {
      continue;
    }
    const rawText = normalizeOutlineText(rawNode.text || rawNode.label || id);
    const nodeType = String(rawNode.type || "").toUpperCase();
    if (isPageOutlineNode(id, nodeType)) {
      result.push(...normalizeBackendOutlineNodes(rawNode.children ?? [], context));
      continue;
    }
    if (isDocumentChromeOutlineNode(id, nodeType, rawText)) {
      continue;
    }
    const isTableNode = nodeType === "TABLE";
    const isTextNode = nodeType === "TEXT";
    const label = isTextNode
      ? formatTextLabel(rawText)
      : isTableNode
        ? formatTableLabel(context.currentHeaderText, rawText, rawNode)
        : formatHeaderLabel(rawText);
    const node: DocumentOutlineNode = {
      id,
      label,
      level: context.level,
      children: [],
    };
    context.items.push({ id, label, level: context.level });
    if (context.parentId) {
      context.parentById.set(id, context.parentId);
    }
    const currentOutlineId = isTableNode ? context.currentOutlineId : id;
    const currentHeaderText = isTableNode ? context.currentHeaderText : rawText;
    context.byElementId.set(id, id);
    context.labelByElementId.set(id, label);
    node.children = normalizeBackendOutlineNodes(rawNode.children ?? [], {
      parentId: id,
      level: context.level + 1,
      currentOutlineId,
      currentHeaderText,
      items: context.items,
      parentById: context.parentById,
      byElementId: context.byElementId,
      labelByElementId: context.labelByElementId,
    });
    result.push(node);
  }
  return result;
}

function isPageOutlineNode(id: string, nodeType: string): boolean {
  return nodeType === "PAGE" || /^page_\d+/i.test(id);
}

function isDocumentChromeOutlineNode(id: string, nodeType: string, text: string): boolean {
  if (["PAGE_NUMBER", "PAGE_HEADER", "PAGE_FOOTER"].includes(nodeType)) {
    return true;
  }
  if (/^page[-_\s]*\d+$/i.test(text)) {
    return true;
  }
  return /_b\d+$/i.test(id) && /^[A-Z0-9-]{5,}v\d+$/i.test(text);
}

function enrichElementLabelsFromHtml(
  document: Document,
  context: {
    items: DocumentOutlineItem[];
    byElementId: Map<string, string>;
    labelByElementId: Map<string, string>;
  },
) {
  let currentOutlineId = "";
  let currentHeaderText = "";
  const headingIds = new Set(context.items.map((item) => item.id));
  for (const element of Array.from(document.body.querySelectorAll<HTMLElement>("[id]"))) {
    if (headingIds.has(element.id) || isHeaderElement(element)) {
      currentOutlineId = element.id;
      currentHeaderText = normalizeOutlineText(element.textContent || "");
    }
    if (currentOutlineId) {
      context.byElementId.set(element.id, currentOutlineId);
    }
    context.labelByElementId.set(element.id, buildElementDisplayLabel(element, currentHeaderText));
  }
}

function buildElementDisplayLabel(element: HTMLElement, currentHeaderText: string): string {
  const id = element.id;
  const text = normalizeOutlineText(element.textContent || "");
  if (isHeaderElement(element)) {
    return formatHeaderLabel(text || id);
  }
  if (isTableElement(element)) {
    return formatTableLabel(currentHeaderText, text);
  }
  if (isTableRowElement(element)) {
    return formatTableRowLabel(currentHeaderText, element, id);
  }
  if (isPageElement(element)) {
    return `Page ${getPageNumberFromId(id) || id}`;
  }
  if (isDocumentChromeElement(element, text)) {
    return "";
  }
  return currentHeaderText ? `${truncateLabel(currentHeaderText)} 中的内容` : id;
}

function isHeaderElement(element: HTMLElement): boolean {
  const tagName = element.tagName.toLowerCase();
  const dataType = (element.getAttribute("data-type") || "").toLowerCase();
  const className = element.getAttribute("class") || "";
  return /^h[1-6]$/.test(tagName) || dataType.includes("title") || dataType.includes("section_header") || className.includes("title");
}

function isTableElement(element: HTMLElement): boolean {
  const tagName = element.tagName.toLowerCase();
  const dataType = (element.getAttribute("data-type") || "").toLowerCase();
  const className = element.getAttribute("class") || "";
  return tagName === "table" || dataType.includes("table") || className.includes("block-table");
}

function isTableRowElement(element: HTMLElement): boolean {
  return element.tagName.toLowerCase() === "tr" || /_tr_\d+$/.test(element.id);
}

function isPageElement(element: HTMLElement): boolean {
  return element.tagName.toLowerCase() === "section" && /^page_\d+/.test(element.id);
}

function isDocumentChromeElement(element: HTMLElement, text: string): boolean {
  const dataType = (element.getAttribute("data-type") || "").toLowerCase();
  const className = element.getAttribute("class") || "";
  if (dataType === "page_number" || dataType === "page_header" || dataType === "page_footer") {
    return true;
  }
  if (className.includes("page-number") || className.includes("block-page_footer") || className.includes("block-page_header")) {
    return true;
  }
  return /^page[-_\s]*\d+$/i.test(text);
}

function formatHeaderLabel(text: string): string {
  const label = truncateLabel(text);
  return label ? `Header: ${label}` : "Header";
}

function formatTextLabel(text: string): string {
  const label = truncateLabel(text);
  return label ? `Text: ${label}` : "Text";
}

function formatTableLabel(headerText: string, fallbackText: string, rawNode?: ReplayOutlineNode): string {
  const header = truncateLabel(headerText);
  const fallback = truncateLabel(readString(rawNode?.label) || fallbackText);
  if (header) {
    return `${header} 下面的表格`;
  }
  return fallback ? `表格：${fallback}` : "表格";
}

function formatTableRowLabel(headerText: string, element: HTMLElement, fallbackId: string): string {
  const header = truncateLabel(headerText);
  const rowIndex = getTableRowIndex(fallbackId);
  const prefix = header ? `${header} 下面的表格` : "表格";
  if (rowIndex === 0) {
    return `${prefix}表头`;
  }
  if (rowIndex !== null) {
    return `${prefix}第 ${rowIndex} 行`;
  }
  const text = truncateLabel(element.textContent || "");
  return text ? `${prefix}行：${text}` : `${prefix}行`;
}

function getTableRowIndex(id: string): number | null {
  const match = id.match(/_tr_(\d+)$/);
  return match ? Number(match[1]) : null;
}

function getPageNumberFromId(id: string): string {
  const match = id.match(/^page_0*(\d+)/);
  return match?.[1] ?? "";
}

function formatEvidenceLabel(evidenceId: string, outline: DocumentOutline): string {
  if (evidenceId.startsWith("/")) {
    const [path, selector = ""] = evidenceId.split("#");
    const fileName = path.split("/").filter(Boolean).at(-1) || path;
    return selector ? `${selector} · ${fileName}` : fileName;
  }
  return outline.labelByElementId.get(evidenceId) || evidenceId;
}

function formatReasonText(reason: string, outline: DocumentOutline): string {
  if (!reason) {
    return "";
  }
  return reason.replace(/\b(?:p\d{3}_b\d{3}(?:_(?:tr|item)_\d{3}|_list|_table)?|page_\d{3})\b/g, (id) =>
    formatEvidenceLabel(id, outline),
  );
}

function truncateLabel(text: string, maxLength = 32): string {
  const label = normalizeOutlineText(text);
  if (label.length <= maxLength) {
    return label;
  }
  return `${label.slice(0, maxLength - 1)}…`;
}

function getActiveOutlineId(outline: DocumentOutline, currentIds: string[]): string {
  for (const id of currentIds) {
    if (outline.items.some((item) => item.id === id)) {
      return id;
    }
    const outlineId = outline.byElementId.get(id);
    if (outlineId) {
      return outlineId;
    }
  }
  return "";
}

function getOutlinePathIds(outline: DocumentOutline, id: string): string[] {
  const path: string[] = [];
  let current = outline.parentById.get(id);
  while (current) {
    path.push(current);
    current = outline.parentById.get(current);
  }
  return [...path.reverse(), id];
}

function normalizeOutlineText(text: string): string {
  return text.replace(/\s+/g, " ").trim();
}

function readObject(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function readString(value: unknown): string {
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number") {
    return String(value);
  }
  return "";
}

function readNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function readStringArray(value: unknown): string[] | null {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : null;
}

function readObjectArray(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value)
    ? value.map((item) => readObject(item)).filter((item): item is Record<string, unknown> => Boolean(item))
    : [];
}
