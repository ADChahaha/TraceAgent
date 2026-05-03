"use client";

import * as React from "react";
import { Check, ChevronRight, ClipboardList, Expand, Gauge, History, Loader2, MousePointerClick, Pause, Play, X } from "lucide-react";

import { stringifyValue } from "@/lib/json";
import type { ReplayAction, ReplayFieldState, ReplayOutlineNode, TaskReplay, TaskResultField } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

type ReplayMode = "auto" | "paused" | "backlog";

type ReplayField = {
  sourceName: string;
  fieldName: string;
  status: string;
  value: unknown;
  evidenceIds: string[];
};

type HighlightState = {
  currentIds: string[];
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

type PlanReplayItem = {
  index: number;
  text: string;
  status: "pending" | "in_progress" | "completed";
  reason: string;
};

const BASE_ACTION_MS = 2600;
const TEXT_READ_DELAY_MS = 900;
const OUTLINE_STEP_MS = 520;
const DOCUMENT_READ_DELAY_MS = 520;
const DOCUMENT_LINE_SCAN_MS = 340;

export function ReplayReview({
  replay,
  finalFields,
  reviewSlot
}: {
  replay: TaskReplay | null;
  finalFields: TaskResultField[];
  reviewSlot?: React.ReactNode;
}) {
  const actions = React.useMemo(() => replay?.actions ?? [], [replay?.actions]);
  const [index, setIndex] = React.useState(0);
  const [mode, setMode] = React.useState<ReplayMode>("paused");
  const [speed, setSpeed] = React.useState(0.75);
  const [iframeHtml, setIframeHtml] = React.useState("");
  const [manualOutlineId, setManualOutlineId] = React.useState("");
  const [manualOutlineTick, setManualOutlineTick] = React.useState(0);
  const [animatedPathIndex, setAnimatedPathIndex] = React.useState(-1);
  const [iframeInteractionTick, setIframeInteractionTick] = React.useState(0);
  const [replayCursor, setReplayCursor] = React.useState<ReplayCursor>({
    visible: true,
    x: 48,
    y: 120,
    clickTick: 0,
  });
  const [expandedOutlineIds, setExpandedOutlineIds] = React.useState<Set<string>>(() => new Set());
  const reviewRef = React.useRef<HTMLElement | null>(null);
  const iframeRef = React.useRef<HTMLIFrameElement | null>(null);
  const outlineScrollRef = React.useRef<HTMLDivElement | null>(null);
  const outlineRefs = React.useRef(new Map<string, HTMLButtonElement>());
  const userInspectingRef = React.useRef(false);

  React.useEffect(() => {
    const timeout = window.setTimeout(() => {
      setIndex(0);
      setMode("paused");
      setManualOutlineId("");
      setIframeHtml(replay?.display_html ? buildReplayHtml(replay.display_html) : "");
    }, 0);
    return () => window.clearTimeout(timeout);
  }, [replay?.display_html, replay?.task_id]);

  const currentAction = actions[index] ?? null;
  const currentActionType = currentAction ? getActionType(currentAction) : "";
  const currentReason = currentAction ? getActionReason(currentAction) : "";
  const currentSetFieldName =
    currentAction && currentActionType === "set_field" ? getSetFieldPayload(currentAction).name : "";
  const backlogActions = React.useMemo(
    () =>
      actions.slice(0, index + 1).map((action, actionIndex) => ({
        action,
        actionIndex,
        reason: getActionReason(action),
      })),
    [actions, index],
  );
  const planItems = React.useMemo(
    () => reducePlanItems(replay?.broad_plan, actions.slice(0, index + 1)),
    [actions, index, replay?.broad_plan],
  );
  const documentOutline = React.useMemo<DocumentOutline>(
    () => buildDocumentOutline(replay?.display_html ?? "", replay?.outline_tree ?? []),
    [replay?.display_html, replay?.outline_tree],
  );
  const currentDisplayReason = React.useMemo(
    () => formatReasonText(currentReason, documentOutline),
    [currentReason, documentOutline],
  );
  const replayFields = React.useMemo(
    () => reduceReplayFields(actions.slice(0, index + 1), finalFields),
    [actions, finalFields, index],
  );
  const currentSetField = React.useMemo(
    () => replayFields.find((field) => field.sourceName === currentSetFieldName) ?? null,
    [currentSetFieldName, replayFields],
  );
  const highlights = React.useMemo(
    () => getHighlightState(actions.slice(0, index + 1), currentAction),
    [actions, currentAction, index],
  );
  const actionOutlineId = React.useMemo(
    () => getActiveOutlineId(documentOutline, highlights.currentIds),
    [documentOutline, highlights.currentIds],
  );
  const activeOutlineId = userInspectingRef.current && manualOutlineId ? manualOutlineId : actionOutlineId;
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
  const visibleOutlinePathIds = React.useMemo(
    () => new Set(activeOutlinePath.slice(0, Math.max(animatedPathIndex + 1, 0))),
    [activeOutlinePath, animatedPathIndex],
  );

  const goNext = React.useCallback(() => {
    userInspectingRef.current = false;
    setMode("paused");
    setManualOutlineId("");
    setIndex((current) => Math.min(current + 1, Math.max(actions.length - 1, 0)));
  }, [actions.length]);

  const goBacklogPrevious = React.useCallback(() => {
    if (actions.length === 0) {
      return;
    }
    setMode("backlog");
    setManualOutlineId("");
    setIndex((current) => Math.max(current - 1, 0));
  }, [actions.length]);

  React.useEffect(() => {
    clearReadingLineHighlight(iframeRef.current);
    setAnimatedPathIndex(-1);
    applyHighlights(iframeRef.current, highlights, currentActionType === "set_field");
  }, [currentActionType, highlights, index]);

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
      setIndex((current) => Math.min(current + 1, actions.length - 1));
    };
    const runAnimation = async () => {
      await wait(0);
      if (shouldStop()) {
        return;
      }
      setAnimatedPathIndex(-1);
      clearReadingLineHighlight(animationIframe);
      applyHighlights(animationIframe, highlights, currentActionType === "set_field");
      await wait(TEXT_READ_DELAY_MS - 260);
      if (shouldStop()) {
        return;
      }
      for (let pathIndex = 0; pathIndex < activeOutlinePath.length; pathIndex += 1) {
        await wait(pathIndex === 0 ? 260 : OUTLINE_STEP_MS);
        if (shouldStop()) {
          return;
        }
        const outlineId = activeOutlinePath[pathIndex];
        setAnimatedPathIndex(pathIndex);
        setExpandedOutlineIds((current) => {
          const next = new Set(current);
          next.add(outlineId);
          return next;
        });
        scrollOutlineItemIntoView(outlineScrollRef.current, outlineRefs.current.get(outlineId) ?? null);
        await wait(140);
        if (shouldStop()) {
          return;
        }
        const point = getElementPointInContainer(
          reviewRef.current,
          outlineRefs.current.get(outlineId) ?? null,
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
      const readableEvidenceIds = getReadableEvidenceIds(animationIframe, highlights.currentIds);
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
    actions.length,
    activeOutlineId,
    activeOutlinePath,
    currentActionType,
    highlights,
    index,
    manualOutlineTick,
    mode,
    speed,
  ]);

  function handleDialogueWheel(event: React.WheelEvent) {
    if (actions.length === 0 || event.deltaY >= 0) {
      return;
    }
    event.preventDefault();
    goBacklogPrevious();
  }

  function exitBacklog() {
    setMode("paused");
  }

  function pauseForUserInspection() {
    userInspectingRef.current = true;
    setMode("paused");
    clearReadingLineHighlight(iframeRef.current);
  }

  function toggleAutoMode() {
    setMode((current) => {
      if (current === "auto") {
        return "paused";
      }
      userInspectingRef.current = false;
      setManualOutlineId("");
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
    setMode("paused");
    if (options?.outlineId) {
      setManualOutlineId(options.outlineId);
      setManualOutlineTick((current) => current + 1);
    }
    const nextIndex = findFirstActionIndexForEvidence(actions, evidenceId);
    if (nextIndex >= 0) {
      setIndex(nextIndex);
    }
    window.setTimeout(() => scrollToEvidence(iframeRef.current, evidenceId), 0);
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

  if (!replay) {
    return (
      <div className="rounded-md border border-dashed p-8 text-sm text-muted-foreground">
        暂无 replay 数据。
      </div>
    );
  }

  return (
    <section ref={reviewRef} className="replay-review-root min-h-[calc(100svh-7rem)] space-y-4 bg-background">
      <div
        className={replayCursor.visible ? "replay-cursor is-visible" : "replay-cursor"}
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
            <Badge variant={mode === "auto" ? "success" : mode === "backlog" ? "warning" : "secondary"}>
              {mode}
            </Badge>
            <span className="text-xs text-muted-foreground">AI extraction replay</span>
          </div>
        </div>
        <span className="font-mono text-xs text-muted-foreground">
          {actions.length === 0 ? "0 / 0" : `${index + 1} / ${actions.length}`}
        </span>
      </div>
      <div className="grid gap-4">
        <div className="replay-stage grid gap-4 lg:grid-cols-[18rem_minmax(0,1fr)_21rem]">
        <aside
          className="replay-outline-panel overflow-hidden rounded-md border bg-background"
          onPointerDown={pauseForUserInspection}
          onWheel={pauseForUserInspection}
          onTouchStart={pauseForUserInspection}
        >
          <div className="border-b p-4">
            <h2 className="text-sm font-semibold text-foreground">文档 Overview</h2>
            <p className="mt-1 text-xs text-muted-foreground">当前 action 会同步定位到这里</p>
            <div className="mt-3 flex gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="h-7 flex-1 text-xs"
                onClick={() => setExpandedOutlineIds(new Set(documentOutline.items.map((item) => item.id)))}
              >
                展开全部
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="h-7 flex-1 text-xs"
                onClick={() => setExpandedOutlineIds(new Set())}
              >
                折叠
              </Button>
            </div>
          </div>
          <div ref={outlineScrollRef} className="h-[calc(100%-7.4rem)] space-y-1 overflow-auto p-3">
            {documentOutline.tree.length > 0 ? (
              documentOutline.tree.map((node) => (
                <OutlineTreeNode
                  key={node.id}
                  node={node}
                  activeOutlineId={activeOutlineId}
                  animatedOutlineId={animatedOutlineId}
                  actionIndex={index + manualOutlineTick}
                  expandedIds={expandedOutlineIds}
                  activePathIds={manualOutlineId ? activeOutlinePathIds : visibleOutlinePathIds}
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
        </aside>

        <div className="flex min-h-0 flex-col gap-3">
          <div className="replay-document-panel overflow-hidden rounded-md border bg-white">
            {replay.display_html ? (
              <iframe
                ref={iframeRef}
                title="document replay"
                srcDoc={iframeHtml || buildReplayHtml(replay.display_html)}
                className="h-full w-full bg-white"
                onLoad={() => {
                  applyHighlights(iframeRef.current, highlights, currentActionType === "set_field");
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
        <aside className="replay-plan-panel-slot">
          {planItems.length > 0 ? <ReplayPlanToolPanel items={planItems} documentOutline={documentOutline} /> : null}
        </aside>
        {mode === "backlog" ? (
          <div
            className="replay-backlog"
            onContextMenu={(event) => {
              event.preventDefault();
              exitBacklog();
            }}
            onClick={() => {
              goNext();
            }}
          >
            <div className="replay-backlog-list">
              {backlogActions.map(({ action, actionIndex, reason }) => (
                <button
                  key={`${actionIndex}-${getActionType(action)}-${getActionTarget(action)}`}
                  type="button"
                  className={actionIndex === index ? "replay-backlog-item is-active" : "replay-backlog-item"}
                  onClick={(event) => {
                    event.stopPropagation();
                    setManualOutlineId("");
                    setMode("paused");
                    setIndex(actionIndex);
                  }}
                >
                  <span className="replay-backlog-index">{String(actionIndex + 1).padStart(2, "0")}</span>
                  <span className="replay-backlog-reason">
                    {formatReasonText(reason, documentOutline) || "模型等待下一步动作。"}
                  </span>
                </button>
              ))}
            </div>
            <div className="replay-backlog-actions">
              <Button type="button" variant="outline" size="icon" onClick={exitBacklog} aria-label="关闭 backlog">
                <X className="h-4 w-4" />
              </Button>
              <span className="font-mono text-xs text-muted-foreground">{index + 1} / {actions.length}</span>
            </div>
          </div>
        ) : null}
        </div>

          <div className="replay-dialogue" onWheel={handleDialogueWheel}>
              <div
                className={currentSetField ? "replay-dialogue-main has-field-write" : "replay-dialogue-main"}
                onClick={(event) => {
                  if ((event.target as HTMLElement).closest("button, input, label, .replay-field-write, .replay-plan-call-card")) {
                    return;
                  }
                  goNext();
                }}
              >
                <div className="replay-dialogue-text">
                  <div className="replay-speaker">AI</div>
                  <p className="replay-dialogue-reason">
                    {currentDisplayReason || "等待模型执行下一步。"}
                  </p>
                </div>
                <div className="replay-dialogue-footer">
                  {currentActionType === "update_plan" ? (
                    <PlanToolCallCard key={`plan-${index}`} action={currentAction} documentOutline={documentOutline} />
                  ) : currentSetField ? (
                    <div
                      key={`field-${index}-${currentSetField.sourceName}`}
                      className="replay-field-write"
                      onClick={(event) => event.stopPropagation()}
                      onPointerDown={(event) => event.stopPropagation()}
                      onWheel={(event) => event.stopPropagation()}
                    >
                      <div className="replay-field-write-title">写入字段：{currentSetField.fieldName}</div>
                      <div className="replay-field-write-value">{stringifyValue(currentSetField.value)}</div>
                      {currentSetField.evidenceIds.length > 0 ? (
                        <div className="replay-field-evidence">
                          {currentSetField.evidenceIds.map((evidenceId) => (
                            <button
                              key={evidenceId}
                              type="button"
                              className="replay-field-evidence-chip"
                              title={formatEvidenceLabel(evidenceId, documentOutline)}
                              onClick={(event) => {
                                event.stopPropagation();
                                jumpToEvidence(evidenceId);
                              }}
                            >
                              {formatEvidenceLabel(evidenceId, documentOutline)}
                            </button>
                          ))}
                        </div>
                      ) : null}
                    </div>
                  ) : (
                    <span aria-hidden="true" />
                  )}
                  <div className="replay-dialogue-controls">
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
                      variant={mode === "backlog" ? "default" : "outline"}
                      size="icon"
                      onClick={() => setMode((current) => (current === "backlog" ? "paused" : "backlog"))}
                      disabled={actions.length === 0}
                      aria-label="打开 backlog"
                    >
                      <History className="h-4 w-4" />
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
                    <span className="font-mono text-xs text-muted-foreground">
                      {actions.length === 0 ? "0/0" : `${index + 1}/${actions.length}`}
                    </span>
                  </div>
                </div>
              </div>
          </div>
          {reviewSlot ? <div>{reviewSlot}</div> : null}
      </div>
    </section>
  );
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

function ReplayPlanToolPanel({
  items,
  documentOutline,
}: {
  items: PlanReplayItem[];
  documentOutline: DocumentOutline;
}) {
  const completedCount = items.filter((item) => item.status === "completed").length;
  return (
    <section className="replay-plan-tool-panel">
      <div className="replay-plan-tool-header">
        <span className="inline-flex items-center gap-2">
          <ClipboardList className="h-4 w-4" />
          Plan
        </span>
        <span className="font-mono text-[11px] text-muted-foreground">{completedCount}/{items.length}</span>
      </div>
      <ol className="replay-plan-tool-list">
        {items.map((item) => (
          <li key={`${item.index}-${item.text}`} className={`replay-plan-tool-item is-${item.status}`}>
            <span className="replay-plan-tool-marker">
              {item.status === "completed" ? <Check className="h-3 w-3" /> : item.index}
            </span>
            <span className="replay-plan-tool-text">{stripPlanNumber(item.text)}</span>
            {item.reason ? (
              <span className="replay-plan-tool-reason">{formatReasonText(item.reason, documentOutline)}</span>
            ) : null}
          </li>
        ))}
      </ol>
    </section>
  );
}

function PlanToolCallCard({
  action,
  documentOutline,
}: {
  action: ReplayAction | null;
  documentOutline: DocumentOutline;
}) {
  const args = readObject(action?.args);
  const result = readObject(action?.result);
  const plan = readObject(result?.plan);
  const planIndex = readString(args?.plan_index) || readString(plan?.plan_index);
  const status = readString(args?.status) || readString(plan?.status);
  const reason = readString(args?.reason) || readString(plan?.reason);
  return (
    <div className="replay-plan-call-card">
      <div className="replay-plan-call-title">update_plan {planIndex ? `#${planIndex}` : ""}</div>
      <div className="replay-plan-call-status">{status || "pending"}</div>
      {reason ? <div className="replay-plan-call-reason">{formatReasonText(reason, documentOutline)}</div> : null}
    </div>
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

function reduceReplayFields(actions: ReplayAction[], finalFields: TaskResultField[]): ReplayField[] {
  const fields = new Map<string, ReplayField>();
  for (const field of finalFields) {
    fields.set(field.field_name, {
      sourceName: field.field_name,
      fieldName: field.display_name || field.field_name,
      status: "pending",
      value: null,
      evidenceIds: [],
    });
  }
  for (const action of actions) {
    if (getActionType(action) !== "set_field") {
      continue;
    }
    const payload = getSetFieldPayload(action);
    if (!payload.name) {
      continue;
    }
    const previous = fields.get(payload.name);
    fields.set(payload.name, {
      sourceName: payload.name,
      fieldName: previous?.fieldName || payload.name,
      status: payload.status || "resolved",
      value: payload.value,
      evidenceIds: payload.evidenceIds,
    });
  }
  return Array.from(fields.values());
}

function reducePlanItems(plan: TaskReplay["broad_plan"], actions: ReplayAction[]): PlanReplayItem[] {
  const steps = Array.isArray(plan?.plan) ? plan.plan : [];
  const items = steps.map((step, stepIndex) => ({
    index: stepIndex + 1,
    text: step,
    status: "pending" as PlanReplayItem["status"],
    reason: "",
  }));
  for (const action of actions) {
    if (getActionType(action) !== "update_plan") {
      continue;
    }
    const args = readObject(action.args);
    const result = readObject(action.result);
    const resultPlan = readObject(result?.plan);
    const planIndex = readNumber(args?.plan_index) || readNumber(resultPlan?.plan_index);
    if (!planIndex || planIndex < 1 || planIndex > items.length) {
      continue;
    }
    const status = readString(args?.status) || readString(resultPlan?.status);
    if (status !== "in_progress" && status !== "completed") {
      continue;
    }
    items[planIndex - 1] = {
      ...items[planIndex - 1],
      status,
      reason: readString(args?.reason) || readString(resultPlan?.reason),
    };
  }
  return items;
}

function getHighlightState(_actions: ReplayAction[], currentAction: ReplayAction | null): HighlightState {
  return {
    currentIds: currentAction ? extractHighlightIds(currentAction) : [],
  };
}

function extractHighlightIds(action: ReplayAction): string[] {
  const type = getActionType(action);
  if (type === "table_extraction") {
    const tableIds = extractEvidenceIds(action);
    const rowIds = extractTableExtractionRowIds(action);
    return Array.from(new Set([...tableIds, ...rowIds]));
  }
  return extractEvidenceIds(action);
}

function extractTableExtractionRowIds(action: ReplayAction): string[] {
  const result = readObject(action.result);
  const rows = Array.isArray(result?.rows) ? result.rows : [];
  const ids: string[] = [];
  for (const row of rows) {
    const rowObject = readObject(row);
    const rowId = readString(rowObject?.row_id);
    if (rowId) {
      ids.push(rowId);
    }
    ids.push(...(readStringArray(rowObject?.evidence_ids) ?? []));
  }
  return ids.filter(Boolean);
}

function getSetFieldPayload(action: ReplayAction): {
  name: string;
  value: unknown;
  evidenceIds: string[];
  status: string;
} {
  const resultField = readObject(readObject(action.result)?.field) as ReplayFieldState | null;
  const args = readObject(action.args);
  const name = readString(args?.name) || readString(resultField?.name);
  const evidenceIds = readStringArray(args?.evidence_ids) || readStringArray(resultField?.evidence_ids) || [];
  return {
    name,
    value: args && "value" in args ? args.value : resultField?.value,
    evidenceIds,
    status: readString(args?.status) || readString(resultField?.status) || "resolved",
  };
}

function extractEvidenceIds(action: ReplayAction): string[] {
  const ids = new Set<string>();
  const args = readObject(action.args);
  for (const key of ["element_id", "section_id", "table_id"]) {
    const value = readString(args?.[key]);
    if (value) {
      ids.add(value);
    }
  }
  for (const evidenceId of collectEvidenceIds(action.result)) {
    ids.add(evidenceId);
  }
  for (const ref of action.refs ?? []) {
    if (ref.block_id) {
      ids.add(ref.block_id);
    }
  }
  return Array.from(ids);
}

function collectEvidenceIds(value: unknown): string[] {
  if (!value || typeof value !== "object") {
    return [];
  }
  if (Array.isArray(value)) {
    return value.flatMap(collectEvidenceIds);
  }
  const record = value as Record<string, unknown>;
  const ids = readStringArray(record.evidence_ids) ?? [];
  for (const key of ["row_id", "table_id", "element_id", "section_id"]) {
    const id = readString(record[key]);
    if (id) {
      ids.push(id);
    }
  }
  for (const nested of Object.values(record)) {
    if (nested && typeof nested === "object") {
      ids.push(...collectEvidenceIds(nested));
    }
  }
  return Array.from(new Set(ids));
}

function getActionTarget(action: ReplayAction): string {
  const args = readObject(action.args);
  return (
    readString(args?.section_id) ||
    readString(args?.element_id) ||
    readString(args?.table_id) ||
    readString(args?.name)
  );
}

function getActionReason(action: ReplayAction): string {
  if (getActionType(action) === "update_plan") {
    const args = readObject(action.args);
    const status = readString(args?.status);
    const planIndex = readString(args?.plan_index);
    const reason = readString(args?.reason) || readString(action.metadata?.reason);
    if (status === "completed") {
      return reason || `计划 #${planIndex} 已完成。`;
    }
    if (status === "in_progress") {
      return reason || `开始执行计划 #${planIndex}。`;
    }
  }
  const args = readObject(action.args);
  return readString(args?.reason) || readString(action.metadata?.reason);
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
  for (const id of state.currentIds) {
    const element = document.getElementById(id);
    element?.classList.add("is-current-highlight");
    if (isFieldWrite) {
      element?.classList.add("is-field-write-highlight");
    }
  }
}

function scrollToEvidence(iframe: HTMLIFrameElement | null, evidenceId: string) {
  const element = iframe?.contentDocument?.getElementById(evidenceId);
  element?.scrollIntoView({ behavior: "smooth", block: "center" });
}

function scrollOutlineItemIntoView(container: HTMLDivElement | null, item: HTMLButtonElement | null) {
  if (!container || !item) {
    return;
  }
  const containerRect = container.getBoundingClientRect();
  const itemRect = item.getBoundingClientRect();
  const nextTop = container.scrollTop + itemRect.top - containerRect.top - container.clientHeight * 0.35;
  container.scrollTo({ top: Math.max(0, nextTop), behavior: "smooth" });
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

function getReadableEvidenceIds(iframe: HTMLIFrameElement | null, ids: string[]): string[] {
  const iframeDocument = iframe?.contentDocument;
  if (!iframeDocument) {
    return ids;
  }
  const seen = new Set<string>();
  const readable: string[] = [];
  const fallback: string[] = [];
  for (const id of ids) {
    const element = iframeDocument.getElementById(id);
    if (!element || seen.has(id)) {
      continue;
    }
    seen.add(id);
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
      fallback.push(id);
    } else {
      readable.push(id);
    }
  }
  return readable.length > 0 ? readable : fallback;
}

function getEvidenceReadDuration(iframe: HTMLIFrameElement | null, evidenceIds: string[]): number {
  return evidenceIds.reduce((total, evidenceId) => {
    if (getEvidenceReadMode(iframe, evidenceId) === "block") {
      return total + DOCUMENT_READ_DELAY_MS + getEvidenceBlockReadDuration(iframe, evidenceId);
    }
    const lines = getEvidenceTextLineBoxes(iframe, evidenceId).length;
    return total + DOCUMENT_READ_DELAY_MS + Math.max(1, lines) * DOCUMENT_LINE_SCAN_MS * 2;
  }, 0);
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

function getEvidenceTextLineBoxes(iframe: HTMLIFrameElement | null, evidenceId?: string): TextLineBox[] {
  return getEvidenceReadingLines(iframe, evidenceId);
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
  const rawRects = Array.from(range.getClientRects())
    .filter((rect) => rect.width > 8 && rect.height > 4)
    .map((rect) => ({
      left: rect.left + iframeWindow.scrollX,
      right: rect.right + iframeWindow.scrollX,
      top: rect.top + iframeWindow.scrollY,
      bottom: rect.bottom + iframeWindow.scrollY,
    }));
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
  if (line.top < viewportTop + 72 || line.bottom > viewportBottom - 72) {
    iframeWindow.scrollTo({
      top: Math.max(0, line.top - iframeWindow.innerHeight * 0.36),
      behavior: "smooth",
    });
  }
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

function findFirstActionIndexForEvidence(actions: ReplayAction[], evidenceId: string): number {
  return actions.findIndex((action) => extractEvidenceIds(action).includes(evidenceId));
}

function buildReplayHtml(displayHtml: string): string {
  return `<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<style>
html { scroll-behavior: smooth; }
body { margin: 0; padding: 24px; background: white; color: #1f2937; }
.reading-line {
  border-radius: 3px;
  transition: background 180ms ease, box-shadow 180ms ease;
}
.is-reading-line {
  background: rgba(14, 165, 164, 0.24);
  box-shadow: inset 0 -0.42em 0 rgba(14, 165, 164, 0.24);
}
.is-current-highlight {
  outline: 3px solid #0ea5a4 !important;
  background: rgba(14, 165, 164, 0.12) !important;
  transition: background 180ms ease, outline-color 180ms ease;
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
<body>${displayHtml}</body>
</html>`;
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
    const isTableNode = String(rawNode.type || "").toUpperCase() === "TABLE";
    const label = isTableNode
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

function formatHeaderLabel(text: string): string {
  const label = truncateLabel(text);
  return label ? `Header: ${label}` : "Header";
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

function stripPlanNumber(text: string): string {
  return text.replace(/^\s*\d+[.)、．]\s*/, "").trim();
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
