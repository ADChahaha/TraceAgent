"use client";

import * as React from "react";
import Link from "next/link";
import {
  ChevronRight,
  Gauge,
  Loader2,
  MousePointerClick,
  Paperclip,
  PanelLeftClose,
  PanelLeftOpen,
  Pause,
  Play,
  Plus,
  Search,
  SendHorizonal,
  SquareTerminal,
  X
} from "lucide-react";

import { stringifyValue } from "@/lib/json";
import type { RecentTask } from "@/lib/task-store";
import type { EnumVariantDefinition, ReplayAction, TaskReplay, TaskResultField, TaskSummary } from "@/lib/types";
import type { ReviewField } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

type ReplayMode = "auto" | "paused";
type SidebarResizeSide = "left" | "right";

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

type EvidenceReviewTab = {
  id: string;
  uri: string;
  label: string;
  evidenceId: string;
};

const DEFAULT_LEFT_PANEL_WIDTH = 224;
const DEFAULT_RIGHT_PANEL_WIDTH = 384;
const LEFT_PANEL_MIN_WIDTH = 176;
const LEFT_PANEL_MAX_WIDTH = 360;
const RIGHT_PANEL_MIN_WIDTH = 300;
const RIGHT_PANEL_MAX_WIDTH = 560;
const PANEL_RESIZE_KEY_STEP = 16;

export function ReplayReview({
  taskId,
  summary,
  replay,
  recentTasks = [],
  finalFields,
  reviewFields = [],
  reviewValues = {},
  reviewComment = "",
  isSubmittingReview = false,
  onReviewValueChange,
  onReviewCommentChange,
  onSubmitReview,
}: {
  taskId?: string;
  summary?: TaskSummary | null;
  replay: TaskReplay | null;
  recentTasks?: RecentTask[];
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
  const [index, setIndex] = React.useState(0);
  const [mode, setMode] = React.useState<ReplayMode>("paused");
  const [speed, setSpeed] = React.useState(0.75);
  const [hoveredAgentActionIndex, setHoveredAgentActionIndex] = React.useState<number | null>(null);
  const [isLeftPanelOpen, setIsLeftPanelOpen] = React.useState(true);
  const [reviewTabs, setReviewTabs] = React.useState<EvidenceReviewTab[]>([]);
  const [activeReviewTabId, setActiveReviewTabId] = React.useState("");
  const [composerValue, setComposerValue] = React.useState("");
  const [leftPanelWidth, setLeftPanelWidth] = React.useState(DEFAULT_LEFT_PANEL_WIDTH);
  const [rightPanelWidth, setRightPanelWidth] = React.useState(DEFAULT_RIGHT_PANEL_WIDTH);
  const agentStreamRef = React.useRef<HTMLDivElement | null>(null);

  React.useEffect(() => {
    setIndex(0);
    setMode("paused");
    setReviewTabs([]);
    setActiveReviewTabId("");
  }, [replay?.task_id]);

  React.useEffect(() => {
    const stream = agentStreamRef.current;
    if (stream) {
      stream.scrollTop = stream.scrollHeight;
    }
  }, [index]);

  const visibleActions = React.useMemo(
    () =>
      actions
        .map((action, actionIndex) => ({ action, actionIndex }))
        .filter(({ action }) => shouldDisplayAgentAction(action)),
    [actions],
  );
  const agentStreamActions = React.useMemo(
    () => visibleActions.filter(({ actionIndex }) => actionIndex <= index),
    [index, visibleActions],
  );
  const visibleActionCount = visibleActions.length;
  const currentAction = actions[index] ?? null;
  const currentActionType = currentAction ? getActionType(currentAction) : "";
  const currentSetFieldName =
    currentAction && (currentActionType === "set_field" || currentActionType === "write_field")
      ? getSetFieldPayload(currentAction).name
      : "";
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
  const activeReviewTab = React.useMemo(
    () => reviewTabs.find((tab) => tab.id === activeReviewTabId) ?? null,
    [activeReviewTabId, reviewTabs],
  );
  const shouldShowProgressPanel = !isLeftPanelOpen && !activeReviewTab;
  const shouldShowRightPanel = shouldShowProgressPanel || Boolean(activeReviewTab);
  const currentDocumentTitle = getCurrentDocumentTitle(replay, currentAction);
  const stageStyle = React.useMemo(
    () => ({
      "--replay-left-panel-width": `${leftPanelWidth}px`,
      "--replay-right-panel-width": `${rightPanelWidth}px`,
    }) as React.CSSProperties,
    [leftPanelWidth, rightPanelWidth],
  );

  React.useEffect(() => {
    if (mode !== "auto" || visibleActions.length === 0) {
      return;
    }
    const timeout = window.setTimeout(() => {
      setIndex((current) => getNextVisibleActionIndex(actions, current));
    }, Math.max(260, 900 / Math.max(speed, 0.25)));
    return () => window.clearTimeout(timeout);
  }, [actions, index, mode, speed, visibleActions.length]);

  function goNext() {
    setMode("paused");
    setIndex((current) => getNextVisibleActionIndex(actions, current));
  }

  function jumpToReplayAction(actionIndex: number) {
    setMode("paused");
    setIndex(clampActionIndex(actions, actionIndex));
  }

  function playSingleReplayAction(actionIndex: number) {
    setMode("paused");
    setIndex(clampActionIndex(actions, actionIndex));
  }

  function toggleAutoMode() {
    setMode((current) => (current === "auto" ? "paused" : "auto"));
  }

  function openEvidenceReview(uri: string, label: string) {
    const evidenceId = getEvidenceIdFromUri(uri);
    const tabId = uri || evidenceId || `evidence-${reviewTabs.length + 1}`;
    const nextTab: EvidenceReviewTab = {
      id: tabId,
      uri,
      label: label || evidenceId || "Evidence",
      evidenceId,
    };
    setReviewTabs((current) => {
      const exists = current.some((tab) => tab.id === tabId);
      return exists ? current : [...current, nextTab];
    });
    setActiveReviewTabId(tabId);
  }

  function closeActiveReview() {
    setReviewTabs((current) => {
      const next = current.filter((tab) => tab.id !== activeReviewTabId);
      setActiveReviewTabId(next.at(-1)?.id ?? "");
      return next;
    });
  }

  function startPanelResize(side: SidebarResizeSide, event: React.PointerEvent<HTMLButtonElement>) {
    event.preventDefault();
    const handle = event.currentTarget;
    const startX = event.clientX;
    const startWidth = side === "left" ? leftPanelWidth : rightPanelWidth;
    const pointerId = event.pointerId;

    const updateWidth = (clientX: number) => {
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
        // JSDOM 和旧浏览器没有完整 pointer capture，不影响 window 级拖拽监听。
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
      if (side === "left") {
        setLeftPanelWidth(LEFT_PANEL_MIN_WIDTH);
      } else {
        setRightPanelWidth(RIGHT_PANEL_MAX_WIDTH);
      }
      return;
    }
    if (event.key === "End") {
      event.preventDefault();
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
    if (side === "left") {
      setLeftPanelWidth((current) => clampPanelWidth(current + delta, LEFT_PANEL_MIN_WIDTH, LEFT_PANEL_MAX_WIDTH));
      return;
    }
    setRightPanelWidth((current) => clampPanelWidth(current - delta, RIGHT_PANEL_MIN_WIDTH, RIGHT_PANEL_MAX_WIDTH));
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
      aria-label="Replay 全屏文档工作台"
      className={
        visibleFieldWrite
          ? "replay-review-root replay-review-root-fullscreen replay-task-workbench has-field-write bg-background"
          : "replay-review-root replay-review-root-fullscreen replay-task-workbench bg-background"
      }
    >
      <div className="replay-topbar" aria-label="Replay 顶部工具栏">
        <div className="replay-topbar-main">
          <button
            type="button"
            className="replay-topbar-back"
            aria-label={isLeftPanelOpen ? "关闭任务栏" : "打开任务栏"}
            title={isLeftPanelOpen ? "关闭任务栏" : "打开任务栏"}
            onClick={() => setIsLeftPanelOpen((current) => !current)}
          >
            {isLeftPanelOpen ? <PanelLeftClose className="h-4 w-4" aria-hidden="true" /> : <PanelLeftOpen className="h-4 w-4" aria-hidden="true" />}
          </button>
          <div className="replay-topbar-title" title={`${taskId ?? replay.task_id} / ${currentDocumentTitle}`}>
            {`${taskId ?? replay.task_id} / ${currentDocumentTitle}`}
          </div>
          <span className="sr-only">AI extraction replay</span>
        </div>
        <div className="replay-topbar-status">
          {activeReviewTab ? (
            <button
              type="button"
              className="replay-review-tab-button is-active"
              aria-label="切换 Review 面板"
              onClick={closeActiveReview}
            >
              Review
            </button>
          ) : null}
          {summary ? <ReplayStatusBadge status={summary.status} /> : null}
        </div>
      </div>
      <div
        className="replay-stage replay-stage-fullscreen grid"
        data-left-panel-open={isLeftPanelOpen ? "true" : "false"}
        data-right-panel-open={shouldShowRightPanel ? "true" : "false"}
        style={stageStyle}
      >
        {isLeftPanelOpen ? (
          <aside className="replay-task-sidebar overflow-hidden bg-background" aria-label="任务工作台左侧任务栏">
            <TaskSidebar tasks={recentTasks} activeTaskId={taskId ?? replay.task_id} />
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

        <div className="replay-agent-panel-slot" aria-label="Agent 中间工作区">
          <section className="replay-agent-panel" aria-label="Agent 工具回放">
            <div className="replay-agent-header">
              <span className="replay-agent-title">AI</span>
              <span className="replay-agent-step">
                {visibleActionCount === 0 ? "step 0 of 0" : `step ${agentStreamActions.length} of ${visibleActionCount}`}
              </span>
            </div>
            <div ref={agentStreamRef} className="replay-agent-stream" aria-label="Agent 文字流">
              {agentStreamActions.length > 0 ? (
                agentStreamActions.map(({ action, actionIndex }, visibleIndex) => {
                  const isCurrent = actionIndex === index;
                  const visibleStepNumber = visibleIndex + 1;
                  const reason = getActionReason(action);
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
                        <button type="button" className="replay-agent-message" onClick={goNext}>
                          <span className="replay-agent-reason-text">
                            <EvidenceReasonText text={reason} onOpenEvidence={openEvidenceReview} />
                          </span>
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
                  reviewValue={
                    reviewValues[visibleFieldWrite.sourceName] ??
                    visibleFieldWrite.reviewField?.agent_value ??
                    stringifyValue(visibleFieldWrite.value)
                  }
                  reviewComment={reviewComment}
                  isSubmittingReview={isSubmittingReview}
                  onOpenEvidence={(evidenceId) => openEvidenceReview(`evidence://${taskId ?? replay.task_id}/${evidenceId}`, evidenceId)}
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
              {mode === "auto" ? <Loader2 className="h-4 w-4 animate-spin text-primary" /> : null}
              <span className="ml-auto font-mono text-xs text-muted-foreground">
                {actions.length === 0 ? "0/0" : `${index + 1}/${actions.length}`}
              </span>
            </div>
            <form
              className="replay-agent-composer"
              aria-label="Agent 对话区"
              onSubmit={(event) => {
                event.preventDefault();
                setComposerValue("");
              }}
            >
              <textarea
                aria-label="Agent 对话输入框"
                value={composerValue}
                onChange={(event) => setComposerValue(event.currentTarget.value)}
                placeholder="Ask for follow-up changes"
              />
              <div className="replay-agent-composer-actions">
                <Button type="button" variant="ghost" size="icon" aria-label="添加文件">
                  <Paperclip className="h-4 w-4" aria-hidden="true" />
                </Button>
                <Button type="submit" size="icon" aria-label="发送消息">
                  <SendHorizonal className="h-4 w-4" aria-hidden="true" />
                </Button>
              </div>
            </form>
          </section>
        </div>

        {shouldShowRightPanel ? (
          <>
            <PanelResizeHandle
              side="right"
              width={rightPanelWidth}
              onPointerDown={(event) => startPanelResize("right", event)}
              onKeyDown={(event) => resizePanelByKeyboard("right", event)}
            />
            <aside className="replay-right-panel-slot">
              {activeReviewTab ? (
                <EvidenceReviewPanel
                  tab={activeReviewTab}
                  replay={replay}
                  fields={replayFields}
                  onClose={closeActiveReview}
                />
              ) : (
                <ProgressPanel
                  summary={summary}
                  replay={replay}
                  visibleActionCount={visibleActionCount}
                  currentStep={agentStreamActions.length}
                  actionIndex={index}
                  actionCount={actions.length}
                />
              )}
            </aside>
          </>
        ) : null}
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

function TaskSidebar({
  tasks,
  activeTaskId,
}: {
  tasks: RecentTask[];
  activeTaskId: string;
}) {
  return (
    <div className="replay-task-sidebar-inner">
      <div className="replay-task-sidebar-header">
        <span className="replay-task-sidebar-label">Tasks</span>
        <Link href="/" className="replay-new-task-link" aria-label="新任务">
          <Plus className="h-4 w-4" aria-hidden="true" />
          <span>新任务</span>
        </Link>
      </div>
      <nav className="replay-task-list" aria-label="最近任务">
        {tasks.length > 0 ? (
          tasks.map((task) => (
            <Link
              key={task.task_id}
              href={`/tasks/${task.task_id}`}
              className={task.task_id === activeTaskId ? "replay-task-item is-active" : "replay-task-item"}
            >
              <span className="replay-task-id">{task.task_id}</span>
              <span className="replay-task-meta">
                {task.status} / {task.stage}
              </span>
              {task.route ? <span className="replay-task-route">{task.route}</span> : null}
              {task.error_message ? <span className="replay-task-error">{task.error_message}</span> : null}
            </Link>
          ))
        ) : (
          <p className="replay-task-empty">暂无最近任务。</p>
        )}
      </nav>
    </div>
  );
}

function ProgressPanel({
  summary,
  replay,
  visibleActionCount,
  currentStep,
  actionIndex,
  actionCount,
}: {
  summary?: TaskSummary | null;
  replay: TaskReplay;
  visibleActionCount: number;
  currentStep: number;
  actionIndex: number;
  actionCount: number;
}) {
  const stream = summary?.stream;
  const items = [
    { label: "status", value: summary?.status ?? replay.status },
    { label: "stage", value: summary?.stage ?? replay.stage },
    { label: "route", value: summary?.route ?? replay.audit?.route ?? "pending" },
    { label: "stream", value: stream?.state ?? (isTerminalStatus(summary?.status ?? replay.status) ? "ended" : "running") },
    { label: "last seq", value: String(stream?.last_event_seq ?? 0) },
    { label: "replay", value: actionCount === 0 ? "0/0" : `${actionIndex + 1}/${actionCount}` },
  ];
  return (
    <section className="replay-progress-panel" aria-label="任务进度面板">
      <div className="replay-side-panel-header">
        <div>
          <div className="replay-side-panel-title">Progress</div>
          <div className="replay-side-panel-subtitle">
            {currentStep} of {visibleActionCount} visible steps
          </div>
        </div>
      </div>
      <ul className="replay-progress-list">
        {items.map((item) => (
          <li key={item.label} className="replay-progress-item">
            <span className="replay-progress-label">{item.label}</span>
            <span className="replay-progress-value">{item.label === "last seq" ? `last seq ${item.value}` : item.value}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function EvidenceReviewPanel({
  tab,
  replay,
  fields,
  onClose,
}: {
  tab: EvidenceReviewTab;
  replay: TaskReplay;
  fields: ReplayField[];
  onClose: () => void;
}) {
  const evidenceText = getEvidenceText(replay.actions, tab.evidenceId);
  return (
    <section className="replay-evidence-review-panel" aria-label="证据 Review 面板">
      <div className="replay-side-panel-header">
        <div>
          <div className="replay-side-panel-title">Review</div>
          <div className="replay-side-panel-subtitle">{tab.label}</div>
        </div>
        <Button type="button" variant="ghost" size="icon" aria-label="关闭 Review" onClick={onClose}>
          <X className="h-4 w-4" aria-hidden="true" />
        </Button>
      </div>
      <div className="replay-evidence-uri">{tab.uri}</div>
      <div className="replay-evidence-review-body">
        <section className="replay-evidence-block" aria-label="证据内容">
          <div className="replay-evidence-block-label">Evidence</div>
          <p>{evidenceText || "当前证据只包含 URI，backend 未返回可直接展示的证据文本。"}</p>
        </section>
        {fields.length > 0 ? (
          <section className="replay-evidence-field-list" aria-label="相关字段">
            <div className="replay-evidence-block-label">Fields</div>
            {fields.map((field) => (
              <div key={field.sourceName} className="replay-evidence-field-row">
                <span>{field.fieldName}</span>
                <Badge variant={field.route === "reject" ? "destructive" : field.route === "review" ? "warning" : "secondary"}>
                  {field.route ?? field.status}
                </Badge>
              </div>
            ))}
          </section>
        ) : null}
      </div>
    </section>
  );
}

function ReplayStatusBadge({ status }: { status: TaskSummary["status"] }) {
  if (status === "completed") {
    return <Badge variant="success">{status}</Badge>;
  }
  if (status === "waiting_review" || status === "processing" || status === "pending") {
    return <Badge variant="warning">{status}</Badge>;
  }
  if (status === "failed" || status === "rejected") {
    return <Badge variant="destructive">{status}</Badge>;
  }
  return <Badge variant="secondary">{status}</Badge>;
}

function EvidenceReasonText({
  text,
  onOpenEvidence,
}: {
  text: string;
  onOpenEvidence: (uri: string, label: string) => void;
}) {
  const parts = React.useMemo(() => parseEvidenceMarkdownLinks(text), [text]);
  return (
    <>
      {parts.map((part, partIndex) => {
        if (part.href) {
          return (
            <a
              key={`${part.href}-${partIndex}`}
              href={part.href}
              className="replay-evidence-link"
              onClick={(event) => {
                event.preventDefault();
                event.stopPropagation();
                onOpenEvidence(part.href ?? "", part.text);
              }}
            >
              {part.text}
            </a>
          );
        }
        return <React.Fragment key={`${part.text}-${partIndex}`}>{part.text}</React.Fragment>;
      })}
    </>
  );
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

function ReplayFieldWriteCard({
  field,
  reviewValue,
  reviewComment,
  isSubmittingReview,
  onOpenEvidence,
  onReviewValueChange,
  onReviewCommentChange,
  onSubmitReview,
}: {
  field: ReplayField;
  reviewValue: unknown;
  reviewComment: string;
  isSubmittingReview: boolean;
  onOpenEvidence: (evidenceId: string) => void;
  onReviewValueChange?: (fieldName: string, value: unknown) => void;
  onReviewCommentChange?: (value: string) => void;
  onSubmitReview?: () => void;
}) {
  const valueText = formatFieldDisplayValue(field);
  return (
    <div
      className="replay-field-write"
      aria-label="字段写入区"
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
                title={evidenceId}
                onClick={(event) => {
                  event.stopPropagation();
                  onOpenEvidence(evidenceId);
                }}
              >
                {evidenceId}
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
          <EnumFieldReviewEditor field={field} value={editorValue} onValueChange={onValueChange} />
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

function reduceReplayFields(
  visibleActions: ReplayAction[],
  finalFields: TaskResultField[],
  reviewFields: ReviewField[],
): ReplayField[] {
  const byName = new Map<string, ReplayField>();
  for (const field of finalFields) {
    byName.set(field.field_name, {
      sourceName: field.field_name,
      fieldName: field.display_name || field.field_name,
      fieldType: field.field_type,
      variants: field.variants ?? [],
      status: field.field_status || "resolved",
      value: field.final_value ?? field.review_value ?? field.agent_value,
      evidenceIds: [],
      route: field.route,
      routeReason: readString(field.route_reason),
      needsReview: field.route === "review",
    });
  }
  for (const field of reviewFields) {
    const existing = byName.get(field.field_name);
    byName.set(field.field_name, {
      sourceName: field.field_name,
      fieldName: field.display_name || existing?.fieldName || field.field_name,
      fieldType: field.field_type ?? existing?.fieldType,
      variants: field.variants ?? existing?.variants ?? [],
      status: field.field_status || existing?.status || "needs_review",
      value: existing?.value ?? field.agent_value,
      evidenceIds: existing?.evidenceIds ?? [],
      route: existing?.route ?? "review",
      routeReason: field.review_reason || existing?.routeReason || null,
      needsReview: field.needs_review,
      reviewField: field,
    });
  }
  for (const action of visibleActions) {
    const actionType = getActionType(action);
    if (actionType !== "set_field" && actionType !== "write_field") {
      continue;
    }
    const payload = getSetFieldPayload(action);
    if (!payload.name) {
      continue;
    }
    const existing = byName.get(payload.name);
    byName.set(payload.name, {
      sourceName: payload.name,
      fieldName: existing?.fieldName || payload.name,
      fieldType: existing?.fieldType,
      variants: existing?.variants ?? [],
      status: payload.status || existing?.status || "resolved",
      value: payload.value ?? existing?.value,
      evidenceIds: payload.evidenceIds.length > 0 ? payload.evidenceIds : existing?.evidenceIds ?? [],
      route: existing?.route,
      routeReason: existing?.routeReason || payload.reason || null,
      needsReview: existing?.needsReview ?? false,
      reviewField: existing?.reviewField,
    });
  }
  return Array.from(byName.values());
}

function getSetFieldPayload(action: ReplayAction): {
  name: string;
  value: unknown;
  status: string;
  evidenceIds: string[];
  reason: string | null;
} {
  const args = readObject(action.args);
  const result = readObject(action.result);
  const resultField = readObject(result?.field);
  const fieldEvidence = readArray(resultField?.evidence);
  const argsEvidence = readArray(args?.final_evidence) ?? readArray(args?.evidence_ids);
  return {
    name: readString(args?.field_id) || readString(args?.name) || readString(resultField?.field_id) || readString(resultField?.name),
    value: args?.value ?? resultField?.value,
    status: readString(args?.status) || readString(resultField?.status) || "resolved",
    evidenceIds: normalizeEvidenceIds(fieldEvidence ?? argsEvidence),
    reason: readString(resultField?.reason) || readString(action.reason),
  };
}

function normalizeEvidenceIds(values: unknown[] | null): string[] {
  if (!values) {
    return [];
  }
  const ids: string[] = [];
  for (const value of values) {
    if (typeof value === "string") {
      ids.push(value);
      continue;
    }
    const objectValue = readObject(value);
    if (!objectValue) {
      continue;
    }
    const path = readString(objectValue.path);
    const selectors = [
      ...readStringArray(objectValue.sentences),
      ...readStringArray(objectValue.items),
      ...readStringArray(objectValue.rows),
      ...readStringArray(objectValue.selectors),
    ];
    if (path && selectors.length > 0) {
      ids.push(...selectors.map((selector) => `${path}#${selector}`));
    } else if (path) {
      ids.push(path);
    }
  }
  return Array.from(new Set(ids));
}

function shouldDisplayAgentAction(action: ReplayAction): boolean {
  return getActionType(action) !== "anchors";
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
  return clampActionIndex(actions, currentIndex);
}

function clampActionIndex(actions: ReplayAction[], actionIndex: number): number {
  return Math.max(0, Math.min(actionIndex, Math.max(actions.length - 1, 0)));
}

function clampPanelWidth(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, Math.round(value)));
}

function getActionType(action: ReplayAction): string {
  return action.tool_name || action.action_type || "";
}

function getActionReason(action: ReplayAction): string {
  return readString(action.reason);
}

function getActionTarget(action: ReplayAction): string {
  const args = readObject(action.args);
  const result = readObject(action.result);
  const resultField = readObject(result?.field);
  return (
    readString(args?.path) ||
    readString(result?.path) ||
    readString(args?.field_id) ||
    readString(args?.name) ||
    readString(resultField?.field_id) ||
    readString(resultField?.name) ||
    readString(args?.query) ||
    ""
  );
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

function isReadToolName(toolName: string): boolean {
  return toolName === "read" || toolName === "read_element" || toolName === "read_section";
}

function getReadActionKind(action: ReplayAction): string {
  const args = readObject(action.args);
  const result = readObject(action.result);
  const path = readString(args?.path) || readString(result?.path);
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

function getCurrentDocumentTitle(replay: TaskReplay | null, currentAction: ReplayAction | null): string {
  if (!replay) {
    return "no replay";
  }
  const path = currentAction ? getActionTarget(currentAction) : "";
  const firstPathPart = path.split("/").filter(Boolean)[0] ?? "";
  const documentIndexMatch = firstPathPart.match(/^(\d+)/);
  const documentIndex = documentIndexMatch ? Number(documentIndexMatch[1]) - 1 : 0;
  return replay.documents[documentIndex]?.filename || replay.documents[0]?.filename || "workspace";
}

function getPathBasename(path: string): string {
  return path.split("/").filter(Boolean).at(-1) || path;
}

function getEvidenceText(actions: ReplayAction[], evidenceId: string): string {
  for (const action of actions) {
    const result = readObject(action.result);
    const resultField = readObject(result?.field);
    const evidenceText = findEvidenceTextInValue(result?.evidence_texts, evidenceId) || findEvidenceTextInValue(resultField?.evidence_texts, evidenceId);
    if (evidenceText) {
      return evidenceText;
    }
  }
  return "";
}

function findEvidenceTextInValue(value: unknown, evidenceId: string): string {
  if (!Array.isArray(value)) {
    return "";
  }
  for (const item of value) {
    const objectItem = readObject(item);
    if (!objectItem) {
      continue;
    }
    const selector = readString(objectItem.selector);
    const path = readString(objectItem.path);
    const text = readString(objectItem.text);
    if (text && (selector === evidenceId || `${path}#${selector}` === evidenceId || evidenceId.endsWith(selector))) {
      return text;
    }
  }
  return "";
}

function parseEvidenceMarkdownLinks(text: string): Array<{ text: string; href?: string }> {
  const parts: Array<{ text: string; href?: string }> = [];
  const linkPattern = /\[([^\]]+)\]\((evidence:\/\/[^)\s]+)\)/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = linkPattern.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push({ text: text.slice(lastIndex, match.index) });
    }
    parts.push({ text: match[1], href: match[2] });
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < text.length) {
    parts.push({ text: text.slice(lastIndex) });
  }
  return parts.length > 0 ? parts : [{ text }];
}

function getEvidenceIdFromUri(uri: string): string {
  try {
    const parsed = new URL(uri);
    const lastPathPart = parsed.pathname.split("/").filter(Boolean).at(-1) ?? "";
    if (parsed.hash) {
      return parsed.hash.slice(1);
    }
    return lastPathPart || parsed.hostname;
  } catch {
    const withoutScheme = uri.replace(/^evidence:\/\//, "");
    return withoutScheme.split("/").filter(Boolean).at(-1) ?? "";
  }
}

function formatFieldDisplayValue(field: ReplayField): string {
  if (isTaggedEnumValue(field.value)) {
    return `${field.value.variant}${field.value.value === null ? "" : `: ${stringifyValue(field.value.value)}`}`;
  }
  return stringifyValue(field.value);
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
    value,
  };
}

function normalizeReviewEditorValue(field: ReplayField, value: unknown): unknown {
  if (isEnumReviewField(field)) {
    return toEnumReviewValue(field, value);
  }
  return value;
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

function isTerminalStatus(status: TaskSummary["status"] | string | undefined): boolean {
  return status === "completed" || status === "failed" || status === "rejected";
}

function readObject(value: unknown): Record<string, unknown> | null {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  return null;
}

function readArray(value: unknown): unknown[] | null {
  return Array.isArray(value) ? value : null;
}

function readString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function readNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function readStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}
