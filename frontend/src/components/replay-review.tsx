"use client";

import * as React from "react";
import Link from "next/link";
import {
  BookUser,
  BookmarkPlus,
  ChevronDown,
  ChevronRight,
  FileCheck,
  FileSearch,
  ListTree,
  Paperclip,
  PanelLeftClose,
  PanelLeftOpen,
  PenLine,
  Plus,
  SendHorizonal,
  X,
} from "lucide-react";

import { stringifyValue } from "@/lib/json";
import type { RecentTask } from "@/lib/task-store";
import type { ReplayAction, TaskReplay, TaskResultField, TaskSummary } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

type SidebarResizeSide = "left" | "field-progress";

type ReplayField = {
  sourceName: string;
  fieldName: string;
  status: string;
  value: unknown;
  evidenceIds: string[];
  summary: string;
};

type WorkspaceSourceTab = {
  id: string;
  uri: string;
  label: string;
  evidenceId: string;
  documentIndex: number;
};

type EvidenceDetail = {
  id: string;
  text: string;
  sourceText: string;
  selector: string;
  documentTitle: string;
  field: ReplayField | null;
};

type AgentBalanceSide = "left" | "right" | "none";
type VisibleAgentAction = {
  action: ReplayAction;
  actionIndex: number;
  visibleStepNumber: number;
};
type AgentStreamItem =
  | { kind: "message"; item: VisibleAgentAction; reason: string }
  | { kind: "tool"; item: VisibleAgentAction }
  | { kind: "tool-group"; items: VisibleAgentAction[] };

const DEFAULT_LEFT_PANEL_WIDTH = 224;
const DEFAULT_FIELD_PROGRESS_PANEL_WIDTH = 320;
const LEFT_PANEL_MIN_WIDTH = 176;
const LEFT_PANEL_MAX_WIDTH = 360;
const RIGHT_PANEL_MIN_WIDTH = 300;
const RIGHT_PANEL_MAX_WIDTH = 920;
const PANEL_RESIZE_KEY_STEP = 16;
const REVIEW_TAB_ID = "review";

export function ReplayReview({
  taskId,
  summary,
  replay,
  recentTasks = [],
  finalFields,
}: {
  taskId?: string;
  summary?: TaskSummary | null;
  replay: TaskReplay | null;
  recentTasks?: RecentTask[];
  finalFields: TaskResultField[];
}) {
  const actions = React.useMemo(() => replay?.actions ?? [], [replay?.actions]);
  const [isLeftPanelOpen, setIsLeftPanelOpen] = React.useState(true);
  const [sourceTabsByTask, setSourceTabsByTask] = React.useState<Record<string, WorkspaceSourceTab[]>>({});
  const [activeWorkspaceTabByTask, setActiveWorkspaceTabByTask] = React.useState<Record<string, string>>({});
  const [selectedFieldName, setSelectedFieldName] = React.useState("");
  const [composerValue, setComposerValue] = React.useState("");
  const [leftPanelWidth, setLeftPanelWidth] = React.useState(DEFAULT_LEFT_PANEL_WIDTH);
  const [fieldProgressPanelWidth, setFieldProgressPanelWidth] = React.useState(DEFAULT_FIELD_PROGRESS_PANEL_WIDTH);
  const agentStreamRef = React.useRef<HTMLDivElement | null>(null);

  const currentTaskId = taskId ?? replay?.task_id ?? "";

  React.useEffect(() => {
    const stream = agentStreamRef.current;
    if (stream) {
      stream.scrollTop = stream.scrollHeight;
    }
  }, [actions.length]);

  const visibleActions = React.useMemo(
    () =>
      actions
        .map((action, actionIndex) => ({ action, actionIndex }))
        .filter(({ action }) => shouldDisplayAgentAction(action))
        .map((item, visibleIndex) => ({ ...item, visibleStepNumber: visibleIndex + 1 })),
    [actions],
  );
  const agentStreamItems = React.useMemo(() => groupAgentStreamItems(visibleActions), [visibleActions]);
  const visibleActionCount = visibleActions.length;
  const replayFields = React.useMemo(
    () => reduceReplayFields(actions, finalFields),
    [actions, finalFields],
  );
  const fieldProgressFields = React.useMemo(() => orderReplayFieldsForProgress(replayFields), [replayFields]);
  const hasFieldProgressFields = fieldProgressFields.length > 0;
  const defaultSelectedFieldName = fieldProgressFields[0]?.sourceName ?? "";
  const effectiveSelectedFieldName = fieldProgressFields.some((field) => field.sourceName === selectedFieldName)
    ? selectedFieldName
    : defaultSelectedFieldName;
  const evidenceDetailsById = React.useMemo(
    () => (replay ? buildEvidenceDetailsById(replay, fieldProgressFields) : new Map<string, EvidenceDetail>()),
    [fieldProgressFields, replay],
  );
  const sourceTabs = React.useMemo(() => sourceTabsByTask[currentTaskId] ?? [], [currentTaskId, sourceTabsByTask]);
  const activeWorkspaceTabId = activeWorkspaceTabByTask[currentTaskId] ?? REVIEW_TAB_ID;
  const activeSourceTab = React.useMemo(
    () => sourceTabs.find((tab) => tab.id === activeWorkspaceTabId) ?? null,
    [activeWorkspaceTabId, sourceTabs],
  );
  const isSourceTabActive = activeWorkspaceTabId !== REVIEW_TAB_ID;
  const shouldShowFieldProgressPanel = !isLeftPanelOpen && activeWorkspaceTabId === REVIEW_TAB_ID;
  const shouldShowRightReviewPanel = shouldShowFieldProgressPanel || isSourceTabActive;
  const visibleSidePanelCount = (isLeftPanelOpen ? 1 : 0) + (shouldShowRightReviewPanel ? 1 : 0);
  const agentBalanceSide: AgentBalanceSide =
    visibleSidePanelCount === 1 ? (isLeftPanelOpen ? "right" : "left") : "none";
  const agentContentMode = visibleSidePanelCount === 1 ? "centered" : "full";
  const replayTitle = taskId ?? replay?.task_id ?? "";
  const stageColumns = React.useMemo(
    () =>
      [
        ...(isLeftPanelOpen ? ["var(--replay-left-panel-width)", "10px"] : []),
        "minmax(0, 1fr)",
        ...(shouldShowRightReviewPanel ? ["10px", "var(--replay-field-progress-panel-width)"] : []),
      ].join(" "),
    [isLeftPanelOpen, shouldShowRightReviewPanel],
  );
  const stageStyle = React.useMemo(
    () => ({
      "--replay-left-panel-width": `${leftPanelWidth}px`,
      "--replay-field-progress-panel-width": `${fieldProgressPanelWidth}px`,
      "--replay-stage-columns": stageColumns,
    }) as React.CSSProperties,
    [fieldProgressPanelWidth, leftPanelWidth, stageColumns],
  );

  function openEvidenceReview(uri: string, label: string) {
    openSourceTab(uri, label);
  }

  function openSourceTab(uri: string, label: string) {
    if (!replay) {
      return;
    }
    const evidenceId = getEvidenceIdFromUri(uri);
    const documentIndex = getEvidenceDocumentIndex(replay, evidenceId);
    const documentTitle = getEvidenceDocumentTitle(replay, evidenceId);
    const tabId = getSourceDocumentTabId(documentIndex);
    const nextTab: WorkspaceSourceTab = {
      id: tabId,
      uri,
      label: documentTitle || label || evidenceId || "Source",
      evidenceId,
      documentIndex,
    };
    setSourceTabsByTask((current) => {
      const currentTabs = current[currentTaskId] ?? [];
      const exists = currentTabs.some((tab) => tab.id === tabId);
      return {
        ...current,
        [currentTaskId]: exists
          ? currentTabs.map((tab) => (tab.id === tabId ? { ...tab, uri, evidenceId, label: tab.label || nextTab.label, documentIndex } : tab))
          : [...currentTabs, nextTab],
      };
    });
    setActiveWorkspaceTabByTask((current) => ({
      ...current,
      [currentTaskId]: tabId,
    }));
  }

  function openFieldReview(fieldName: string) {
    setSelectedFieldName(fieldName);
  }

  function selectWorkspaceTab(tabId: string) {
    setActiveWorkspaceTabByTask((current) => ({
      ...current,
      [currentTaskId]: tabId,
    }));
  }

  function closeSourceTab(tabId: string) {
    setSourceTabsByTask((current) => ({
      ...current,
      [currentTaskId]: (current[currentTaskId] ?? []).filter((tab) => tab.id !== tabId),
    }));
    setActiveWorkspaceTabByTask((current) => {
      if (current[currentTaskId] !== tabId) {
        return current;
      }
      return {
        ...current,
        [currentTaskId]: REVIEW_TAB_ID,
      };
    });
  }

  function openActionSource(action: ReplayAction, label: string) {
    const uri = getActionEvidenceUri(action);
    if (uri) {
      openSourceTab(uri, label);
    }
  }

  function startPanelResize(side: SidebarResizeSide, event: React.PointerEvent<HTMLButtonElement>) {
    event.preventDefault();
    const handle = event.currentTarget;
    const startX = event.clientX;
    const startWidth = side === "left" ? leftPanelWidth : fieldProgressPanelWidth;
    const pointerId = event.pointerId;

    const updateWidth = (clientX: number) => {
      const deltaX = clientX - startX;
      if (side === "left") {
        setLeftPanelWidth(clampPanelWidth(startWidth + deltaX, LEFT_PANEL_MIN_WIDTH, LEFT_PANEL_MAX_WIDTH));
        return;
      }
      const nextWidth = clampPanelWidth(startWidth - deltaX, RIGHT_PANEL_MIN_WIDTH, RIGHT_PANEL_MAX_WIDTH);
      setFieldProgressPanelWidth(nextWidth);
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
      setPanelWidthToBoundary(side, side === "left" ? LEFT_PANEL_MIN_WIDTH : RIGHT_PANEL_MAX_WIDTH);
      return;
    }
    if (event.key === "End") {
      event.preventDefault();
      setPanelWidthToBoundary(side, side === "left" ? LEFT_PANEL_MAX_WIDTH : RIGHT_PANEL_MIN_WIDTH);
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
    if (side === "field-progress") {
      setFieldProgressPanelWidth((current) => clampPanelWidth(current - delta, RIGHT_PANEL_MIN_WIDTH, RIGHT_PANEL_MAX_WIDTH));
      return;
    }
  }

  function setPanelWidthToBoundary(side: SidebarResizeSide, width: number) {
    if (side === "left") {
      setLeftPanelWidth(width);
      return;
    }
    if (side === "field-progress") {
      setFieldProgressPanelWidth(width);
      return;
    }
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
        hasFieldProgressFields
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
          <div className="replay-topbar-title" title={replayTitle}>
            {replayTitle}
          </div>
          <span className="sr-only">AI extraction replay</span>
        </div>
        <div className="replay-topbar-status">
          {summary ? <ReplayStatusBadge status={summary.status} /> : null}
        </div>
      </div>
      <div
        className="replay-stage replay-stage-fullscreen grid"
        data-left-panel-open={isLeftPanelOpen ? "true" : "false"}
        data-right-panel-open={shouldShowRightReviewPanel ? "true" : "false"}
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

        <ReviewWorkspacePanel
          agentStreamRef={agentStreamRef}
          agentStreamItems={agentStreamItems}
          visibleActionCount={visibleActionCount}
          composerValue={composerValue}
          agentBalanceSide={agentBalanceSide}
          agentContentMode={agentContentMode}
          onComposerChange={setComposerValue}
          onComposerSubmit={() => setComposerValue("")}
          onOpenEvidence={openEvidenceReview}
          onOpenActionSource={openActionSource}
        />

        {shouldShowRightReviewPanel ? (
          <>
            <PanelResizeHandle
              side="field-progress"
              width={fieldProgressPanelWidth}
              onPointerDown={(event) => startPanelResize("field-progress", event)}
              onKeyDown={(event) => resizePanelByKeyboard("field-progress", event)}
            />
            <aside className="replay-review-side-panel-slot" aria-label="右侧 Review 工作栏">
              <WorkspaceTabStrip
                sourceTabs={sourceTabs}
                activeTabId={activeWorkspaceTabId}
                onSelectTab={selectWorkspaceTab}
                onCloseTab={closeSourceTab}
              />
              <div className="replay-review-side-panel-body">
                {activeWorkspaceTabId === REVIEW_TAB_ID ? (
                  <FieldProgressPanel
                    fields={fieldProgressFields}
                    selectedFieldName={effectiveSelectedFieldName}
                    onSelectField={openFieldReview}
                  />
                ) : (
                  <SourceTabPanel
                    tab={activeSourceTab ?? sourceTabs[0] ?? { id: REVIEW_TAB_ID, uri: "", label: "Review", evidenceId: "", documentIndex: 0 }}
                    replay={replay}
                    evidenceDetailsById={evidenceDetailsById}
                  />
                )}
              </div>
            </aside>
          </>
        ) : null}
      </div>
    </section>
  );
}

function AgentBalanceSpacer({ side, active }: { side: "left" | "right"; active: boolean }) {
  return (
    <span
      className="replay-agent-balance-spacer"
      data-agent-balance-spacer={side}
      data-active={active ? "true" : "false"}
      aria-hidden="true"
    />
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

function FieldProgressPanel({
  fields,
  selectedFieldName,
  onSelectField,
}: {
  fields: ReplayField[];
  selectedFieldName: string;
  onSelectField: (fieldName: string) => void;
}) {
  const selectedField = fields.find((field) => field.sourceName === selectedFieldName) ?? fields[0] ?? null;

  return (
    <section className="replay-field-progress-panel" aria-label="字段进度面板">
      <div className="replay-side-panel-header">
        <div>
          <div className="replay-side-panel-title">Field Progress</div>
          <div className="replay-side-panel-subtitle">{fields.length} field{fields.length === 1 ? "" : "s"}</div>
        </div>
      </div>
      <div className="replay-field-progress-list">
        {fields.map((field) => (
          <FieldProgressRow
            key={field.sourceName}
            field={field}
            isSelected={field.sourceName === selectedField?.sourceName}
            onSelect={() => onSelectField(field.sourceName)}
          />
        ))}
        {fields.length === 0 ? (
          <p className="replay-field-progress-empty">暂无字段进度。</p>
        ) : null}
      </div>
    </section>
  );
}

function orderReplayFieldsForProgress(fields: ReplayField[]): ReplayField[] {
  return [...fields].sort((left, right) => left.fieldName.localeCompare(right.fieldName));
}

function FieldProgressRow({
  field,
  isSelected,
  onSelect,
}: {
  field: ReplayField;
  isSelected: boolean;
  onSelect: () => void;
}) {
  const valuePreview = truncateText(formatFieldDisplayValue(field), 88);
  const evidenceText = field.evidenceIds.length === 1 ? "1 evidence" : `${field.evidenceIds.length} evidence`;
  const summaryPreview = truncateText(field.summary, 132);
  return (
    <button
      type="button"
      className={isSelected ? "replay-field-progress-row is-selected" : "replay-field-progress-row"}
      aria-pressed={isSelected}
      aria-label={`${field.fieldName} ${field.status}`}
      title={field.fieldName}
      onClick={onSelect}
    >
      <span className="replay-field-row-main">
        <span className="replay-field-row-title">{field.fieldName}</span>
        <span className="replay-field-row-value">{valuePreview || "暂无字段值"}</span>
        {summaryPreview ? <span className="replay-field-row-summary">{summaryPreview}</span> : null}
      </span>
      <span className="replay-field-row-meta">
        <span>{field.status}</span>
        <span>{evidenceText}</span>
      </span>
    </button>
  );
}

function WorkspaceTabStrip({
  sourceTabs,
  activeTabId,
  onSelectTab,
  onCloseTab,
}: {
  sourceTabs: WorkspaceSourceTab[];
  activeTabId: string;
  onSelectTab: (tabId: string) => void;
  onCloseTab: (tabId: string) => void;
}) {
  return (
    <div className="replay-workspace-tabs" role="tablist" aria-label="右侧工作栏选项卡">
      <button
        type="button"
        role="tab"
        aria-selected={activeTabId === REVIEW_TAB_ID}
        className={activeTabId === REVIEW_TAB_ID ? "replay-workspace-tab is-active" : "replay-workspace-tab"}
        onClick={() => onSelectTab(REVIEW_TAB_ID)}
      >
        <FileSearch className="h-4 w-4" aria-hidden="true" />
        <span>Review</span>
      </button>
      {sourceTabs.map((tab) => (
        <span
          key={tab.id}
          className={activeTabId === tab.id ? "replay-workspace-tab-shell is-active" : "replay-workspace-tab-shell"}
        >
          <button
            type="button"
            role="tab"
            aria-selected={activeTabId === tab.id}
            className="replay-workspace-tab replay-workspace-source-tab"
            onClick={() => onSelectTab(tab.id)}
          >
            {tab.label}
          </button>
          <button
            type="button"
            className="replay-workspace-tab-close"
            aria-label={`关闭 ${tab.label}`}
            onClick={(event) => {
              event.stopPropagation();
              onCloseTab(tab.id);
            }}
          >
            <X className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
        </span>
      ))}
    </div>
  );
}

function ReviewWorkspacePanel({
  agentStreamRef,
  agentStreamItems,
  visibleActionCount,
  composerValue,
  agentBalanceSide,
  agentContentMode,
  onComposerChange,
  onComposerSubmit,
  onOpenEvidence,
  onOpenActionSource,
}: {
  agentStreamRef: React.RefObject<HTMLDivElement | null>;
  agentStreamItems: AgentStreamItem[];
  visibleActionCount: number;
  composerValue: string;
  agentBalanceSide: AgentBalanceSide;
  agentContentMode: "centered" | "full";
  onComposerChange: (value: string) => void;
  onComposerSubmit: () => void;
  onOpenEvidence: (uri: string, label: string) => void;
  onOpenActionSource: (action: ReplayAction, label: string) => void;
}) {
  return (
    <div
      className="replay-agent-panel-slot"
      aria-label="Agent 中间工作区"
      data-agent-balance-side={agentBalanceSide}
      data-agent-content-mode={agentContentMode}
      data-agent-gutter={agentContentMode === "centered" ? "compact" : "none"}
    >
      <section className="replay-agent-panel" aria-label="Agent 工具回放">
        <div className="replay-agent-header">
          <span className="replay-agent-title">AI</span>
          <span className="replay-agent-step">
            {visibleActionCount === 0 ? "0 tool calls" : `${visibleActionCount} tool calls`}
          </span>
        </div>
        <div ref={agentStreamRef} className="replay-agent-stream" aria-label="Agent 文字流">
          <div className="replay-agent-centered-content" aria-label="Agent 居中文字流内容">
            <div className="replay-agent-content-frame" aria-label="Agent 中间文字框">
              <AgentBalanceSpacer side="left" active={agentContentMode === "centered"} />
              <div className="replay-agent-readable-column" aria-label="Agent 阅读列">
                {agentStreamItems.length > 0 ? (
                  agentStreamItems.map((streamItem) => {
                    if (streamItem.kind === "message") {
                      const { action, actionIndex, visibleStepNumber } = streamItem.item;
                      const toolName = getActionType(action) || "tool";
                      const target = getActionTarget(action);
                      return (
                        <div
                          key={`message-${actionIndex}-${toolName}-${target}`}
                          aria-label={`第 ${visibleStepNumber} 步 ${toolName} 文字`}
                          className="replay-agent-turn replay-agent-message-turn"
                        >
                          <div className="replay-agent-message">
                            <span className="replay-agent-reason-text">
                              <EvidenceReasonText text={streamItem.reason} onOpenEvidence={onOpenEvidence} />
                            </span>
                          </div>
                        </div>
                      );
                    }
                    if (streamItem.kind === "tool-group") {
                      const firstItem = streamItem.items[0];
                      return (
                        <AgentToolGroup
                          key={`tool-group-${firstItem.actionIndex}-${streamItem.items.length}`}
                          items={streamItem.items}
                          onOpenActionSource={onOpenActionSource}
                        />
                      );
                    }
                    const { action, actionIndex, visibleStepNumber } = streamItem.item;
                    const toolName = getActionType(action) || "tool";
                    const target = getActionTarget(action);
                    const ok = isAgentActionOk(action);
                    return (
                      <div
                        key={`${actionIndex}-${toolName}-${target}`}
                        aria-label={`第 ${visibleStepNumber} 步 ${toolName}`}
                        className="replay-agent-turn"
                      >
                        <AgentToolLine action={action} ok={ok} onOpenActionSource={onOpenActionSource} />
                      </div>
                    );
                  })
                ) : (
                  <div className="replay-agent-turn is-current">
                    <div className="replay-agent-empty">等待工具调用。</div>
                  </div>
                )}
              </div>
              <AgentBalanceSpacer side="right" active={agentContentMode === "centered"} />
            </div>
          </div>
        </div>
        <form
          className="replay-agent-composer"
          aria-label="Agent 对话区"
          onSubmit={(event) => {
            event.preventDefault();
            onComposerSubmit();
          }}
        >
          <div className="replay-agent-composer-balance-row" aria-label="Agent 居中输入区">
            <div className="replay-agent-composer-frame" aria-label="Agent 中间输入框">
              <AgentBalanceSpacer side="left" active={agentContentMode === "centered"} />
              <div className="replay-agent-composer-readable-column" aria-label="Agent 输入阅读列">
                <textarea
                  aria-label="Agent 对话输入框"
                  value={composerValue}
                  onChange={(event) => onComposerChange(event.currentTarget.value)}
                  placeholder="Ask for follow-up changes"
                  className="replay-agent-composer-input"
                />
                <div className="replay-agent-composer-actions">
                  <Button type="button" variant="ghost" size="icon" aria-label="添加文件">
                    <Paperclip className="h-4 w-4" aria-hidden="true" />
                  </Button>
                  <Button type="submit" size="icon" aria-label="发送消息">
                    <SendHorizonal className="h-4 w-4" aria-hidden="true" />
                  </Button>
                </div>
              </div>
              <AgentBalanceSpacer side="right" active={agentContentMode === "centered"} />
            </div>
          </div>
        </form>
      </section>
    </div>
  );
}

function SourceTabPanel({
  tab,
  replay,
  evidenceDetailsById,
}: {
  tab: WorkspaceSourceTab;
  replay: TaskReplay;
  evidenceDetailsById: Map<string, EvidenceDetail>;
}) {
  const activeEvidenceDetail = getEvidenceDetailById(evidenceDetailsById, tab.evidenceId);
  const highlightSelector = activeEvidenceDetail?.selector || getEvidenceSelector(tab.evidenceId);
  const sourceFrameRef = React.useRef<HTMLIFrameElement | null>(null);
  const renderedDocumentHtml = React.useMemo(
    () => renderSourceDocumentHtml(replay.display_html, highlightSelector),
    [highlightSelector, replay.display_html],
  );
  const scrollToCurrentEvidence = React.useCallback(() => {
    const target = sourceFrameRef.current?.contentDocument?.querySelector<HTMLElement>("[data-current-evidence='true']");
    if (target && typeof target.scrollIntoView === "function") {
      target.scrollIntoView({ block: "center", inline: "nearest" });
    }
  }, []);

  React.useEffect(() => {
    scrollToCurrentEvidence();
  }, [renderedDocumentHtml, scrollToCurrentEvidence]);

  return (
    <div
      className="replay-source-panel-slot"
      aria-label="原文查看器"
      data-highlight-selector={highlightSelector}
    >
      <iframe
        ref={sourceFrameRef}
        title="原文文档"
        className="replay-source-document replay-source-frame"
        srcDoc={renderedDocumentHtml}
        referrerPolicy="no-referrer"
        onLoad={scrollToCurrentEvidence}
      />
    </div>
  );
}

function ReplayStatusBadge({ status }: { status: TaskSummary["status"] }) {
  if (status === "completed") {
    return <Badge variant="success">{status}</Badge>;
  }
  if (status === "processing" || status === "pending") {
    return <Badge variant="warning">{status}</Badge>;
  }
  if (status === "failed") {
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
  ok = isAgentActionOk(action),
  onOpenActionSource,
}: {
  action: ReplayAction;
  ok?: boolean;
  onOpenActionSource?: (action: ReplayAction, label: string) => void;
}) {
  const toolName = getActionType(action) || "tool";
  const summary = formatAgentToolSummary(action, ok);
  const meta = collectAgentToolMeta(action, ok);
  const toolIcon = getAgentToolIcon(toolName);
  const ToolIcon = toolIcon.icon;
  const lineText = [summary, ...meta].filter(Boolean).join(" · ");
  const evidenceUri = getActionEvidenceUri(action);
  const canOpenSource = Boolean(onOpenActionSource && evidenceUri);
  const content = (
    <>
      <ToolIcon className="replay-agent-tool-icon" aria-hidden="true" />
      <span className="replay-agent-tool-summary">{lineText}</span>
    </>
  );
  const className = [
    "replay-agent-tool-line",
    toolIcon.isReading ? "is-read-tool" : "",
    ok ? "" : "is-failed",
  ].filter(Boolean).join(" ");
  if (canOpenSource) {
    return (
      <a
        href={evidenceUri}
        className={className}
        aria-label={`tool ${toolName}`}
        data-tool-icon={toolIcon.name}
        onClick={(event) => {
          event.preventDefault();
          event.stopPropagation();
          onOpenActionSource?.(action, summary);
        }}
      >
        {content}
      </a>
    );
  }
  return (
    <div
      className={className}
      aria-label={`tool ${toolName}`}
      data-tool-icon={toolIcon.name}
    >
      {content}
    </div>
  );
}

function AgentToolGroup({
  items,
  onOpenActionSource,
}: {
  items: VisibleAgentAction[];
  onOpenActionSource?: (action: ReplayAction, label: string) => void;
}) {
  const [isExpanded, setIsExpanded] = React.useState(false);
  const summaryText = summarizeAgentToolGroup(items);
  return (
    <div className="replay-agent-tool-group" role="group" aria-label={`${items.length} collapsed tools`}>
      <button
        type="button"
        className="replay-agent-tool-group-toggle"
        aria-expanded={isExpanded}
        aria-label={`${isExpanded ? "收起" : "展开"} ${items.length} 个工具调用`}
        onClick={() => setIsExpanded((current) => !current)}
      >
        {isExpanded ? (
          <ChevronDown className="replay-agent-tool-group-icon" aria-hidden="true" />
        ) : (
          <ChevronRight className="replay-agent-tool-group-icon" aria-hidden="true" />
        )}
        <span className="replay-agent-tool-group-summary">{summaryText}</span>
      </button>
      {isExpanded ? (
        <div className="replay-agent-tool-group-lines">
          {items.map(({ action, actionIndex }) => (
            <AgentToolLine
              key={`${actionIndex}-${getActionType(action)}-${getActionTarget(action)}`}
              action={action}
              onOpenActionSource={onOpenActionSource}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}

function summarizeAgentToolGroup(items: VisibleAgentAction[]): string {
  const explorationCount = items.filter(({ action }) => isExplorationTool(getActionType(action))).length;
  const savedEvidenceCount = items.filter(({ action }) => getActionType(action) === "add_candidate_evidence").length;
  const reviewedEvidenceCount = items.filter(({ action }) => getActionType(action) === "review_evidences").length;
  const fieldCount = items.filter(({ action }) => getActionType(action) === "write_field").length;
  const unknownCount = items.length - explorationCount - savedEvidenceCount - reviewedEvidenceCount - fieldCount;
  const clauses: string[] = [];

  if (explorationCount > 0) {
    clauses.push(`Explored ${explorationCount} file${explorationCount === 1 ? "" : "s"}`);
  }
  if (savedEvidenceCount > 0) {
    clauses.push(`${clauses.length > 0 ? "saved" : "Saved"} ${savedEvidenceCount} evidence item${savedEvidenceCount === 1 ? "" : "s"}`);
  }
  if (reviewedEvidenceCount > 0) {
    clauses.push(`${clauses.length > 0 ? "reviewed" : "Reviewed"} ${reviewedEvidenceCount} evidence set${reviewedEvidenceCount === 1 ? "" : "s"}`);
  }
  if (fieldCount > 0) {
    clauses.push(`${clauses.length > 0 ? "filled" : "Filled"} ${fieldCount} field${fieldCount === 1 ? "" : "s"}`);
  }
  if (unknownCount > 0) {
    clauses.push(`${clauses.length > 0 ? "ran" : "Ran"} ${unknownCount} tool${unknownCount === 1 ? "" : "s"}`);
  }

  return clauses.length > 0 ? clauses.join(", ") : `Ran ${items.length} tools`;
}

function isExplorationTool(toolName: string): boolean {
  return toolName === "tree" || toolName === "read";
}

function reduceReplayFields(
  visibleActions: ReplayAction[],
  finalFields: TaskResultField[],
): ReplayField[] {
  const byName = new Map<string, ReplayField>();
  for (const field of finalFields) {
    byName.set(field.field_name, {
      sourceName: field.field_name,
      fieldName: field.display_name || field.field_name,
      status: field.field_status || "resolved",
      value: field.final_value ?? field.agent_value,
      evidenceIds: [],
      summary: "",
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
      status: payload.status || existing?.status || "resolved",
      value: payload.value ?? existing?.value,
      evidenceIds: payload.evidenceIds.length > 0 ? payload.evidenceIds : existing?.evidenceIds ?? [],
      summary: payload.reason || existing?.summary || "",
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
  return !["anchors", "submit_result"].includes(getActionType(action));
}

function groupAgentStreamItems(actions: VisibleAgentAction[]): AgentStreamItem[] {
  const items: AgentStreamItem[] = [];
  let pendingTools: VisibleAgentAction[] = [];

  const flushPendingTools = () => {
    if (pendingTools.length === 0) {
      return;
    }
    if (pendingTools.length === 1) {
      items.push({ kind: "tool", item: pendingTools[0] });
    } else {
      items.push({ kind: "tool-group", items: pendingTools });
    }
    pendingTools = [];
  };

  for (const item of actions) {
    const reason = getActionReason(item.action);
    if (reason) {
      flushPendingTools();
      items.push({ kind: "message", item, reason });
    }
    pendingTools.push(item);
  }
  flushPendingTools();
  return items;
}

function isAgentActionOk(action: ReplayAction): boolean {
  return readObject(action.result)?.ok !== false;
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

function getActionEvidenceUri(action: ReplayAction): string {
  const toolName = getActionType(action);
  const args = readObject(action.args);
  const result = readObject(action.result);
  const resultField = readObject(result?.field);
  const candidates = [
    readString(args?.path_id),
    readString(args?.locator),
    readString(args?.path),
    readString(result?.locator),
    readString(result?.path_id),
    readString(result?.path),
    ...readStringArray(result?.candidate_evidence),
    ...readStringArray(result?.evidence),
    ...readStringArray(resultField?.candidate_evidence),
    ...readStringArray(resultField?.evidence),
  ];
  const usable = candidates.find((value) => isEvidenceLikeReference(value));
  if (!usable) {
    return "";
  }
  if (usable.startsWith("evidence://")) {
    return usable;
  }
  if (/^p\d+_b\d+/.test(usable) || /^S\d+/.test(usable)) {
    return `evidence://${usable}`;
  }
  if (usable.includes("#")) {
    return `evidence://${usable.split("#").at(-1) ?? usable}`;
  }
  if (toolName === "read" || toolName === "add_candidate_evidence") {
    return `evidence://${usable}`;
  }
  return "";
}

function isEvidenceLikeReference(value: string): boolean {
  if (!value) {
    return false;
  }
  return value.startsWith("evidence://") || value.includes("#") || /^p\d+_b\d+/.test(value) || /^S\d+/.test(value);
}

function formatAgentToolSummary(action: ReplayAction, ok: boolean): string {
  const toolName = getActionType(action) || "tool";
  const args = readObject(action.args);
  const result = readObject(action.result);
  const resultField = readObject(result?.field);
  const field = readString(args?.field_id) || readString(result?.field_id) || readString(resultField?.field_id) || readString(args?.name) || readString(resultField?.name);
  if (toolName === "tree") {
    return ok ? "Viewed outline" : "Outline failed";
  }
  if (toolName === "read") {
    return ok ? "Read passage" : "Read failed";
  }
  if (toolName === "add_candidate_evidence") {
    return field ? `Saved evidence for ${field}` : "Saved evidence";
  }
  if (toolName === "review_evidences") {
    return field ? `Reviewed evidence for ${field}` : "Reviewed evidence";
  }
  if (toolName === "write_field") {
    return field ? `Filled ${field}` : "Filled field";
  }
  if (toolName === "submit_result") {
    return ok ? "Submitted result" : "Submit failed";
  }
  if (field) {
    return field;
  }
  return ok ? "Ran tool" : "Tool failed";
}

function collectAgentToolMeta(action: ReplayAction, ok: boolean): string[] {
  const result = readObject(action.result);
  const meta: string[] = [];
  if (!ok) {
    const errors = Array.isArray(result?.errors) ? result.errors : [];
    const firstError = readObject(errors[0]);
    const message = readString(firstError?.message);
    if (message) {
      meta.push(message);
    }
  }
  return meta.slice(0, 2);
}

function getAgentToolIcon(toolName: string): { icon: React.ComponentType<{ className?: string; "aria-hidden"?: "true" }>; name: string; isReading?: boolean } {
  if (toolName === "tree") {
    return { icon: ListTree, name: "list-tree", isReading: true };
  }
  if (toolName === "read") {
    return { icon: BookUser, name: "book-user", isReading: true };
  }
  if (toolName === "add_candidate_evidence") {
    return { icon: BookmarkPlus, name: "bookmark-plus" };
  }
  if (toolName === "review_evidences") {
    return { icon: FileCheck, name: "file-check" };
  }
  if (toolName === "write_field") {
    return { icon: PenLine, name: "pen-line" };
  }
  return { icon: PenLine, name: "tool" };
}

function buildEvidenceDetailsById(replay: TaskReplay, fields: ReplayField[]): Map<string, EvidenceDetail> {
  const details = new Map<string, EvidenceDetail>();
  const sourceBlocks = extractDisplayHtmlBlocks(replay.display_html);
  const fieldsByEvidenceId = new Map<string, ReplayField>();

  for (const field of fields) {
    for (const evidenceId of field.evidenceIds) {
      fieldsByEvidenceId.set(evidenceId, field);
      fieldsByEvidenceId.set(getEvidenceSelector(evidenceId), field);
    }
  }

  for (const action of replay.actions) {
    const result = readObject(action.result);
    const resultField = readObject(result?.field);
    for (const value of [result?.evidence_texts, resultField?.evidence_texts]) {
      collectEvidenceDetails(value, replay, sourceBlocks, fieldsByEvidenceId, details);
    }
  }

  for (const [selector, sourceText] of sourceBlocks) {
    if (details.has(selector)) {
      continue;
    }
    details.set(selector, {
      id: selector,
      text: sourceText,
      sourceText,
      selector,
      documentTitle: getEvidenceDocumentTitle(replay, selector),
      field: findFieldByEvidenceText(fields, sourceText),
    });
  }

  for (const field of fields) {
    for (const evidenceId of field.evidenceIds) {
      if (getEvidenceDetailById(details, evidenceId)) {
        continue;
      }
      const selector = getEvidenceSelector(evidenceId);
      const sourceText = sourceBlocks.get(selector) ?? "";
      details.set(evidenceId, {
        id: evidenceId,
        text: sourceText || evidenceId,
        sourceText,
        selector,
        documentTitle: getEvidenceDocumentTitle(replay, evidenceId),
        field,
      });
    }
  }

  return details;
}

function collectEvidenceDetails(
  value: unknown,
  replay: TaskReplay,
  sourceBlocks: Map<string, string>,
  fieldsByEvidenceId: Map<string, ReplayField>,
  details: Map<string, EvidenceDetail>,
) {
  if (!Array.isArray(value)) {
    return;
  }
  for (const item of value) {
    const objectItem = readObject(item);
    if (!objectItem) {
      continue;
    }
    const selector = readString(objectItem.selector);
    const path = readString(objectItem.path);
    const text = readString(objectItem.text);
    const id = path && selector ? `${path}#${selector}` : selector || path;
    if (!id) {
      continue;
    }
    const sourceText = sourceBlocks.get(selector) || text;
    const detail: EvidenceDetail = {
      id,
      text: text || sourceText || id,
      sourceText,
      selector,
      documentTitle: getEvidenceDocumentTitle(replay, id),
      field: fieldsByEvidenceId.get(id) ?? fieldsByEvidenceId.get(selector) ?? null,
    };
    details.set(id, detail);
    if (selector) {
      details.set(selector, detail);
    }
    for (const [fieldEvidenceId, field] of fieldsByEvidenceId) {
      if (fieldEvidenceId.endsWith(selector) || fieldEvidenceId.endsWith(`#${selector}`)) {
        details.set(fieldEvidenceId, { ...detail, id: fieldEvidenceId, field });
      }
    }
  }
}

function getEvidenceDetailById(details: Map<string, EvidenceDetail>, evidenceId: string): EvidenceDetail | null {
  const exact = details.get(evidenceId) ?? details.get(getEvidenceSelector(evidenceId));
  if (exact) {
    return exact;
  }
  const selector = getEvidenceSelector(evidenceId);
  for (const [id, detail] of details) {
    if (id.endsWith(selector) || id.endsWith(`#${selector}`)) {
      return detail;
    }
  }
  return null;
}

function extractDisplayHtmlBlocks(displayHtml: string): Map<string, string> {
  const blocks = new Map<string, string>();
  if (!displayHtml) {
    return blocks;
  }
  const blockPattern = /<[^>]*\bid=["']([^"']+)["'][^>]*>([\s\S]*?)<\/[^>]+>/g;
  let match: RegExpExecArray | null;
  while ((match = blockPattern.exec(displayHtml)) !== null) {
    blocks.set(match[1], decodeHtmlText(stripHtml(match[2])));
  }
  return blocks;
}

const SOURCE_FRAME_STYLE = `<style data-agent-gate-source-frame>
html,
body {
  width: 100% !important;
  max-width: 100% !important;
  overflow-x: hidden !important;
  overflow-y: auto !important;
}
body {
  margin: 0 !important;
  background: #ffffff !important;
}
main {
  width: 100% !important;
  max-width: 100% !important;
  min-width: 0 !important;
  margin: 0 !important;
  padding: 0 !important;
  box-sizing: border-box !important;
}
.page {
  box-sizing: border-box !important;
  width: 100% !important;
  max-width: 100% !important;
  min-width: 0 !important;
  margin: 0 !important;
  padding: 24px !important;
  border-radius: 0 !important;
  box-shadow: none !important;
  overflow-wrap: anywhere !important;
  word-break: normal !important;
}
table {
  width: 100% !important;
  max-width: 100% !important;
  table-layout: fixed !important;
  border-collapse: collapse;
}
.table-wrap {
  width: 100% !important;
  max-width: 100% !important;
  overflow-x: hidden !important;
}
.table-wrap table {
  width: 100% !important;
  max-width: 100% !important;
}
img,
svg,
canvas,
video {
  max-width: 100% !important;
  height: auto !important;
}
p,
li,
td,
th,
pre,
code {
  max-width: 100% !important;
  white-space: pre-wrap !important;
  overflow-wrap: anywhere !important;
  word-break: normal !important;
}
.is-current-evidence,
[data-current-evidence="true"] {
  border-radius: 6px !important;
  background: rgba(51, 156, 255, 0.18) !important;
  color: #171717 !important;
  outline: 2px solid rgba(51, 156, 255, 0.55) !important;
  outline-offset: 2px !important;
  scroll-margin: 48px !important;
}
</style>`;

function renderSourceDocumentHtml(displayHtml: string, highlightSelector: string): string {
  if (!displayHtml) {
    return wrapSourceDocumentHtml("<p>No source document is available.</p>");
  }
  let renderedHtml = displayHtml;
  const escapedSelector = escapeRegExp(highlightSelector);
  const openingTagPattern = new RegExp(`(<[^>]*\\bid=(["'])${escapedSelector}\\2[^>]*)(>)`, "i");
  if (highlightSelector) {
    renderedHtml = displayHtml.replace(openingTagPattern, (match, openingTag: string, _quote: string, close: string) => {
      if (/\bdata-current-evidence=/.test(openingTag)) {
        return match;
      }
      const classMatch = /\bclass=(["'])([^"']*)\1/i.exec(openingTag);
      if (classMatch) {
        const nextClass = `${classMatch[2]} is-current-evidence`.trim();
        const withClass = openingTag.replace(classMatch[0], `class=${classMatch[1]}${nextClass}${classMatch[1]}`);
        return `${withClass} data-current-evidence="true"${close}`;
      }
      return `${openingTag} class="is-current-evidence" data-current-evidence="true"${close}`;
    });
  }
  return wrapSourceDocumentHtml(renderedHtml);
}

function wrapSourceDocumentHtml(displayHtml: string): string {
  const sanitizedHtml = stripExecutableSourceHtml(displayHtml);
  const htmlWithMarker = /<html\b/i.test(sanitizedHtml)
    ? sanitizedHtml.replace(/<html\b([^>]*)>/i, (match, attrs: string) => {
        if (/\bdata-agent-gate-source-frame\b/i.test(attrs)) {
          return match;
        }
        return `<html${attrs} data-agent-gate-source-frame>`;
      })
    : `<!doctype html><html data-agent-gate-source-frame><head><meta charset="utf-8"></head><body>${sanitizedHtml}</body></html>`;

  if (/<\/head>/i.test(htmlWithMarker)) {
    return htmlWithMarker.replace(/<\/head>/i, `${SOURCE_FRAME_STYLE}</head>`);
  }
  if (/<head\b[^>]*>/i.test(htmlWithMarker)) {
    return htmlWithMarker.replace(/<head\b[^>]*>/i, (match) => `${match}${SOURCE_FRAME_STYLE}`);
  }
  return htmlWithMarker.replace(/<html\b[^>]*>/i, (match) => `${match}<head><meta charset="utf-8">${SOURCE_FRAME_STYLE}</head>`);
}

function stripExecutableSourceHtml(displayHtml: string): string {
  return displayHtml.replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, "");
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function stripHtml(value: string): string {
  return value.replace(/<[^>]*>/g, " ");
}

function decodeHtmlText(value: string): string {
  return value
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, "\"")
    .replace(/&#39;/g, "'")
    .replace(/\s+/g, " ")
    .trim();
}

function getEvidenceSelector(evidenceId: string): string {
  const withoutHash = evidenceId.split("#").at(-1) ?? evidenceId;
  const locator = withoutHash.split("/").filter(Boolean).at(-1) ?? withoutHash;
  return normalizeEvidenceSelector(locator);
}

function getEvidenceDocumentTitle(replay: TaskReplay, evidenceId: string): string {
  const documentIndex = getEvidenceDocumentIndex(replay, evidenceId);
  return formatSourceFilename(replay.documents[documentIndex]?.filename || replay.documents[0]?.filename || "Source");
}

function formatSourceFilename(filename: string): string {
  if (!filename) {
    return filename;
  }
  let decodedFilename = filename;
  try {
    decodedFilename = decodeURIComponent(filename);
  } catch {
    decodedFilename = filename;
  }
  const withoutUrlSuffix = decodedFilename.split(/[?#]/)[0] ?? decodedFilename;
  const normalizedPath = withoutUrlSuffix.replace(/\\/g, "/");
  return normalizedPath.split("/").filter(Boolean).at(-1) || decodedFilename;
}

function getSourceDocumentTabId(documentIndex: number): string {
  return `source-document-${documentIndex}`;
}

function getEvidenceDocumentIndex(replay: TaskReplay, evidenceId: string): number {
  const pathPrefix = evidenceId.split("#")[0] ?? "";
  const firstPathPart = pathPrefix.split("/").filter(Boolean)[0] ?? "";
  const documentIndexMatch = firstPathPart.match(/^(\d+)/);
  const parsedDocumentIndex = documentIndexMatch ? Number(documentIndexMatch[1]) - 1 : 0;
  if (!Number.isFinite(parsedDocumentIndex) || parsedDocumentIndex < 0) {
    return 0;
  }
  return Math.min(parsedDocumentIndex, Math.max(replay.documents.length - 1, 0));
}

function normalizeEvidenceSelector(locator: string): string {
  const dottedMatch = locator.match(/^(?:\d+\.)+\d+$/);
  if (!dottedMatch) {
    return locator;
  }
  const parts = locator.split(".");
  if (parts.length < 3) {
    return locator;
  }
  const pageNumber = Number(parts[1]);
  const blockNumber = Number(parts[2]);
  if (!Number.isFinite(pageNumber) || !Number.isFinite(blockNumber)) {
    return locator;
  }
  return `p${String(pageNumber).padStart(3, "0")}_b${String(blockNumber).padStart(3, "0")}`;
}

function findFieldByEvidenceText(fields: ReplayField[], evidenceText: string): ReplayField | null {
  const normalizedEvidenceText = normalizeComparableText(evidenceText);
  if (!normalizedEvidenceText) {
    return null;
  }
  return (
    fields.find((field) => {
      const normalizedValue = normalizeComparableText(formatFieldDisplayValue(field));
      return normalizedValue ? normalizedEvidenceText.includes(normalizedValue) : false;
    }) ?? null
  );
}

function normalizeComparableText(value: string): string {
  return value
    .replace(/[，、]/g, ",")
    .replace(/\s+/g, "")
    .trim()
    .toLowerCase();
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
    if (parsed.hash) {
      return parsed.hash.slice(1);
    }
    const pathParts = parsed.pathname.split("/").filter(Boolean);
    return [parsed.hostname, ...pathParts].filter(Boolean).join("/") || parsed.hostname;
  } catch {
    const withoutScheme = uri.replace(/^evidence:\/\//, "");
    return withoutScheme.split("/").filter(Boolean).join("/");
  }
}

function truncateText(value: string, maxLength: number): string {
  const text = value.replace(/\s+/g, " ").trim();
  if (text.length <= maxLength) {
    return text;
  }
  return `${text.slice(0, Math.max(0, maxLength - 1))}…`;
}

function stableDomId(value: string): string {
  return value.replace(/[^a-zA-Z0-9_-]+/g, "-");
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

function readStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}
