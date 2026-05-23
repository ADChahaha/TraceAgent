"use client";

import * as React from "react";
import Link from "next/link";
import {
  ArrowLeft,
  BookOpenText,
  CheckCircle2,
  ChevronRight,
  Clock3,
  X,
  Eye,
  FileSearch,
  Pause,
  Plus,
  Search,
  SendHorizonal,
  Wrench
} from "lucide-react";

import {
  cancelTask as defaultCancelTask,
  createTaskEventSource as defaultCreateTaskEventSource,
  createTaskInput as defaultCreateTaskInput,
  listTasks as defaultListTasks,
  loadTaskDetail as defaultLoadTaskDetail,
  parseTaskEventMessage,
} from "@/lib/api";
import { getRecentTasks, syncRecentTaskSummaries, updateRecentTask, type RecentTask } from "@/lib/task-store";
import type {
  QaInputCreated,
  TaskDetailData,
  TaskEvent,
  TaskSourceDocument,
  TaskSummary
} from "@/lib/types";
import {
  LeftSidebarResizeHandle,
  RightSidebarResizeHandle,
  useLeftSidebarResize,
  useRightSidebarResize
} from "@/components/sidebar-resize";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { MarkdownEvidence } from "@/components/markdown-evidence";

const TASK_EVENT_NAMES = [
  "message",
  "task.created",
  "document.processed",
  "task.ready",
  "message.created",
  "turn.created",
  "turn.started",
  "agent.event",
  "turn.completed",
  "turn.cancel_requested",
  "turn.cancelled",
  "turn.failed",
  "task.failed",
];

type ActiveEvidenceSource = {
  document: TaskSourceDocument;
  evidenceUri: string;
  label: string;
  openKey: number;
  sourceSelector: string;
  sourceSelectors: string[];
  inlineSelector: string;
  headingText: string;
};

type QaStreamItem =
  | {
      kind: "message";
      seq: number;
      turnId: string | null;
      role: "user" | "assistant";
      content: string;
    }
  | {
      kind: "tool";
      seq: number;
      turnId: string | null;
      toolName: string;
      label: string;
      evidenceUri: string | null;
      ok: boolean;
    }
  | {
      kind: "tool-group";
      groupId: string;
      seq: number;
      turnId: string | null;
      items: Extract<QaStreamItem, { kind: "tool" }>[];
    }
  | {
      kind: "status";
      seq: number;
      turnId: string | null;
      label: string;
    }
  | {
      kind: "thinking";
      seq: number;
      turnId: string | null;
    };

export interface TaskDetailProps {
  taskId: string;
  initialSummary?: TaskSummary;
  loadTaskDetail?: (taskId: string) => Promise<TaskDetailData>;
  listTasks?: () => Promise<TaskSummary[]>;
  createTaskInput?: (taskId: string, content: string) => Promise<QaInputCreated>;
  cancelTask?: (taskId: string) => Promise<unknown>;
  createTaskEventSource?: (taskId: string, afterSeq?: number) => EventSource;
}

export function TaskDetail({
  taskId,
  initialSummary,
  loadTaskDetail = defaultLoadTaskDetail,
  listTasks = defaultListTasks,
  createTaskInput = defaultCreateTaskInput,
  cancelTask = defaultCancelTask,
  createTaskEventSource = defaultCreateTaskEventSource,
}: TaskDetailProps) {
  const [detail, setDetail] = React.useState<TaskDetailData | null>(
    initialSummary
      ? { summary: initialSummary, result: null, trace: null, replay: null, audit: null }
      : null
  );
  const [isLoading, setIsLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [recentTasks, setRecentTasks] = React.useState<RecentTask[]>(() => getRecentTasks());
  const [events, setEvents] = React.useState<TaskEvent[]>([]);
  const [optimisticEvents, setOptimisticEvents] = React.useState<TaskEvent[]>([]);
  const [composerValue, setComposerValue] = React.useState("");
  const [isSubmittingInput, setIsSubmittingInput] = React.useState(false);
  const [isCancelling, setIsCancelling] = React.useState(false);
  const [eventSubscriptionKey, setEventSubscriptionKey] = React.useState(0);
  const [activeEvidenceSource, setActiveEvidenceSource] = React.useState<ActiveEvidenceSource | null>(null);
  const evidenceOpenKeyRef = React.useRef(0);
  const eventCursorRef = React.useRef({ taskId, seq: 0 });
  const composerValueRef = React.useRef("");
  const isRunningRef = React.useRef(false);
  const isCancellingRef = React.useRef(false);
  const summaryRef = React.useRef<TaskSummary | null | undefined>(initialSummary);

  const refresh = React.useCallback(async () => {
    setError(null);
    try {
      const loaded = await loadTaskDetail(taskId);
      setDetail((current) => {
        if (!current) {
          summaryRef.current = loaded.summary;
          return loaded;
        }
        const currentSeq = current.summary.stream?.last_event_seq ?? 0;
        const loadedSeq = loaded.summary.stream?.last_event_seq ?? 0;
        if (currentSeq > loadedSeq) {
          summaryRef.current = current.summary;
          return current;
        }
        summaryRef.current = loaded.summary;
        return loaded;
      });
      setRecentTasks(updateRecentTask(loaded.summary));
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Failed to load task");
    } finally {
      setIsLoading(false);
    }
  }, [loadTaskDetail, taskId]);

  React.useEffect(() => {
    // 初次进入详情页需要从 backend 同步任务快照。
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refresh();
  }, [refresh]);

  React.useEffect(() => {
    let cancelled = false;
    listTasks()
      .then((tasks) => {
        if (!cancelled && tasks.length > 0) {
          setRecentTasks(syncRecentTaskSummaries(tasks));
        }
      })
      .catch(() => {
        // 左侧任务栏可以继续使用本地缓存；详情加载错误由主流程暴露。
      });
    return () => {
      cancelled = true;
    };
  }, [listTasks]);

  const summary = detail?.summary ?? initialSummary;
  const summaryIsRunning = isTaskRunning(summary);
  const isRunning = summaryIsRunning || isSubmittingInput || isCancelling;
  const wasSummaryRunningRef = React.useRef(summaryIsRunning);

  React.useEffect(() => {
    summaryRef.current = summary;
    isRunningRef.current = isRunning;
    isCancellingRef.current = isCancelling;
  }, [isCancelling, isRunning, summary]);

  React.useEffect(() => {
    const wasSummaryRunning = wasSummaryRunningRef.current;
    wasSummaryRunningRef.current = summaryIsRunning;
    if (!wasSummaryRunning || summaryIsRunning) {
      return;
    }
    setIsSubmittingInput(false);
    setIsCancelling(false);
  }, [summaryIsRunning]);

  const openEvidence = React.useCallback((uri: string, label: string) => {
    const source = findEvidenceSource(summary, uri, label);
    if (!source) {
      return;
    }
    evidenceOpenKeyRef.current += 1;
    setActiveEvidenceSource({ ...source, openKey: evidenceOpenKeyRef.current });
  }, [summary]);

  React.useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const afterSeq = eventSubscriptionKey === 0 ? 0 : eventCursorRef.current.seq;
    if (eventSubscriptionKey === 0) {
      eventCursorRef.current = { taskId, seq: 0 };
    }
    const eventSource = createTaskEventSource(taskId, afterSeq);
    const handleMessage = (message: MessageEvent<string>) => {
      const event = parseTaskEventMessage(message);
      if (!event) {
        return;
      }
      eventCursorRef.current = {
        taskId,
        seq: Math.max(eventCursorRef.current.seq, event.seq),
      };
      setEvents((current) => appendTaskEvent(current, event));
      if (event.type === "message.created") {
        setOptimisticEvents((current) => current.filter((item) => !isSameMessageEvent(item, event)));
      }
      isRunningRef.current = !(isTerminalTurnEvent(event) || event.status === "ready");
      const hadReviewDocuments = (summaryRef.current?.documents?.length ?? 0) > 0;
      setDetail((current) => {
        if (!current) {
          return current;
        }
        const nextSummary = applyEventToSummary(current.summary, event);
        summaryRef.current = nextSummary;
        return {
          ...current,
          summary: nextSummary,
        };
      });
      if (isSourceIndexedEvent(event)) {
        if (!hadReviewDocuments) {
          void refresh();
        }
      }
      if (isTerminalTurnEvent(event)) {
        isCancellingRef.current = false;
        setIsSubmittingInput(false);
        setIsCancelling(false);
        void refresh();
      }
    };
    TASK_EVENT_NAMES.forEach((eventName) => {
      eventSource.addEventListener(eventName, handleMessage);
    });
    return () => {
      TASK_EVENT_NAMES.forEach((eventName) => {
        eventSource.removeEventListener(eventName, handleMessage);
      });
      eventSource.close();
    };
  }, [createTaskEventSource, eventSubscriptionKey, refresh, taskId]);

  const handleComposerChange = React.useCallback((value: string) => {
    composerValueRef.current = value;
    setComposerValue(value);
  }, []);

  const handleSubmitQuestion = React.useCallback(async () => {
    const content = composerValueRef.current.trim();
    if (!content || isRunningRef.current) {
      return;
    }
    setError(null);
    const optimisticEvent = createOptimisticUserEvent({
      taskId,
      content,
      afterSeq: eventCursorRef.current.seq,
    });
    setOptimisticEvents((current) => appendTaskEvent(current, optimisticEvent));
    composerValueRef.current = "";
    isRunningRef.current = true;
    setComposerValue("");
    setIsSubmittingInput(true);
    setEventSubscriptionKey((current) => current + 1);
    try {
      await createTaskInput(taskId, content);
      void refresh();
    } catch (inputError) {
      setError(inputError instanceof Error ? inputError.message : "Failed to submit question");
      isRunningRef.current = false;
      setIsSubmittingInput(false);
    }
  }, [createTaskInput, refresh, taskId]);

  const handleComposerKeyDown = React.useCallback((event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (!shouldSubmitComposerOnKeyDown(event)) {
      return;
    }
    event.preventDefault();
    void handleSubmitQuestion();
  }, [handleSubmitQuestion]);

  const handleCancel = React.useCallback(async () => {
    if (!isRunningRef.current || isCancellingRef.current) {
      return;
    }
    setError(null);
    isCancellingRef.current = true;
    isRunningRef.current = true;
    setIsCancelling(true);
    try {
      await cancelTask(taskId);
      setEventSubscriptionKey((current) => current + 1);
      void refresh();
    } catch (cancelError) {
      setError(cancelError instanceof Error ? cancelError.message : "Failed to cancel");
      isCancellingRef.current = false;
      setIsCancelling(false);
    }
  }, [cancelTask, refresh, taskId]);

  const handleComposerPrimaryAction = React.useCallback(() => {
    if (isRunningRef.current) {
      void handleCancel();
      return;
    }
    void handleSubmitQuestion();
  }, [handleCancel, handleSubmitQuestion]);

  const visibleEvents = React.useMemo(() => mergeVisibleEvents(events, optimisticEvents), [events, optimisticEvents]);
  const streamItems = React.useMemo(() => withPendingThinkingItem(buildQaStreamItems(visibleEvents), isRunning), [isRunning, visibleEvents]);

  return (
    <main aria-label="Task detail workspace" className="task-detail-fullscreen-shell">
      {error ? (
        <Alert variant="destructive" className="task-detail-alert">
          <AlertTitle>Task operation failed</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      {summary?.status === "failed" && summary.error_message ? (
        <Alert variant="destructive" className="task-detail-alert">
          <AlertTitle>Task failed</AlertTitle>
          <AlertDescription>{summary.error_message}</AlertDescription>
        </Alert>
      ) : null}

      {isLoading && !detail ? (
        <div className="flex min-h-screen items-center justify-center text-sm text-muted-foreground">Loading task details...</div>
      ) : null}

      {detail ? (
        <QaWorkspace
          taskId={taskId}
          summary={summary}
          recentTasks={recentTasks}
          streamItems={streamItems}
          activeEvidenceSource={activeEvidenceSource}
          composerValue={composerValue}
          isRunning={isRunning}
          onOpenEvidence={openEvidence}
          onComposerChange={handleComposerChange}
          onComposerKeyDown={handleComposerKeyDown}
          onSubmitQuestion={handleSubmitQuestion}
          onComposerPrimaryAction={handleComposerPrimaryAction}
        />
      ) : null}
    </main>
  );
}

function QaWorkspace({
  taskId,
  summary,
  recentTasks,
  streamItems,
  activeEvidenceSource,
  composerValue,
  isRunning,
  onOpenEvidence,
  onComposerChange,
  onComposerKeyDown,
  onSubmitQuestion,
  onComposerPrimaryAction,
}: {
  taskId: string;
  summary?: TaskSummary | null;
  recentTasks: RecentTask[];
  streamItems: QaStreamItem[];
  activeEvidenceSource: ActiveEvidenceSource | null;
  composerValue: string;
  isRunning: boolean;
  onOpenEvidence: (uri: string, label: string) => void;
  onComposerChange: (value: string) => void;
  onComposerKeyDown: (event: React.KeyboardEvent<HTMLTextAreaElement>) => void;
  onSubmitQuestion: () => void;
  onComposerPrimaryAction: () => void;
}) {
  const [isLeftPanelOpen, setIsLeftPanelOpen] = React.useState(true);
  const [closedReviewOpenKey, setClosedReviewOpenKey] = React.useState<number | null>(null);
  const isRightPanelOpen = activeEvidenceSource !== null;
  const isReviewOpen = activeEvidenceSource !== null && activeEvidenceSource.openKey !== closedReviewOpenKey;
  const isVisibleRightPanelOpen = isRightPanelOpen && isReviewOpen;
  const { leftPanelWidth, resizeLeftPanelByKeyboard, startLeftPanelResize } = useLeftSidebarResize();
  const { rightPanelWidth, resizeRightPanelByKeyboard, startRightPanelResize } = useRightSidebarResize();
  const agentBalanceSide = getAgentBalanceSide(isLeftPanelOpen, isVisibleRightPanelOpen);
  const streamRef = React.useRef<HTMLDivElement | null>(null);
  const shouldFollowStreamRef = React.useRef(true);

  React.useLayoutEffect(() => {
    const stream = streamRef.current;
    if (!stream) {
      return;
    }
    if (!shouldFollowStreamRef.current) {
      return;
    }
    stream.scrollTop = stream.scrollHeight;
  }, [streamItems.length]);

  const handleStreamScroll = React.useCallback((event: React.UIEvent<HTMLDivElement>) => {
    shouldFollowStreamRef.current = isElementNearBottom(event.currentTarget);
  }, []);

  return (
    <section
      aria-label="QA document workspace"
      className="replay-review-root replay-review-root-fullscreen replay-task-workbench bg-background"
    >
      <div className="replay-topbar" aria-label="QA top bar">
        <div className="replay-topbar-main">
          <button
            type="button"
            className="replay-topbar-back"
            aria-label={isLeftPanelOpen ? "Close sidebar" : "Open sidebar"}
            title={isLeftPanelOpen ? "Close sidebar" : "Open sidebar"}
            onClick={() => setIsLeftPanelOpen((current) => !current)}
          >
            <ArrowLeft className="h-4 w-4" aria-hidden="true" />
          </button>
          <div className="replay-topbar-title" title={taskId}>{taskId}</div>
        </div>
        <div className="replay-topbar-status">
          {summary ? <StatusBadge status={summary.status} /> : null}
          <span className="qa-document-count">{summary?.document_count ?? 0} docs</span>
        </div>
      </div>
      <div
        className="replay-stage replay-stage-fullscreen grid"
        aria-label="QA stage"
        data-left-panel-open={isLeftPanelOpen ? "true" : "false"}
        data-right-panel-open={isVisibleRightPanelOpen ? "true" : "false"}
        style={{
          "--replay-left-panel-width": `${leftPanelWidth}px`,
          "--replay-right-panel-width": `${rightPanelWidth}px`,
          "--replay-stage-columns": qaStageColumns(isLeftPanelOpen, isVisibleRightPanelOpen),
        } as React.CSSProperties}
      >
        {isLeftPanelOpen ? (
          <aside className="replay-task-sidebar overflow-hidden bg-background" aria-label="Task sidebar">
            <TaskSidebar tasks={recentTasks} activeTaskId={taskId} />
          </aside>
        ) : null}
        {isLeftPanelOpen ? (
          <LeftSidebarResizeHandle
            width={leftPanelWidth}
            onPointerDown={startLeftPanelResize}
            onKeyDown={resizeLeftPanelByKeyboard}
          />
        ) : null}
        <section
          className="replay-agent-panel-slot"
          aria-label="Agent workspace"
          data-agent-balance-side={agentBalanceSide}
          data-agent-content-mode="centered"
          data-agent-gutter="compact"
        >
          <div className="replay-agent-panel" aria-label="Document QA Agent">
            <div
              ref={streamRef}
              className="replay-agent-stream"
              aria-label="QA conversation and reading process"
              onScroll={handleStreamScroll}
            >
              <div className="replay-agent-centered-content">
                <div className="replay-agent-content-frame">
                  <span className="replay-agent-balance-spacer" data-agent-balance-spacer="left" data-active="true" aria-hidden="true" />
                  <div className="replay-agent-readable-column">
                    {streamItems.length > 0 ? (
                      streamItems.map((item) => <QaStreamRow key={streamItemKey(item)} item={item} onOpenEvidence={onOpenEvidence} />)
                    ) : (
                      <div className="replay-agent-turn is-current">
                        <div className="replay-agent-empty">{isRunning ? "Thinking" : "Ask a question to start multi-turn QA."}</div>
                      </div>
                    )}
                  </div>
                  <span className="replay-agent-balance-spacer" data-agent-balance-spacer="right" data-active="true" aria-hidden="true" />
                </div>
              </div>
            </div>
            <QaComposer
              composerValue={composerValue}
              isRunning={isRunning}
              onComposerChange={onComposerChange}
              onComposerKeyDown={onComposerKeyDown}
              onSubmitQuestion={onSubmitQuestion}
              onComposerPrimaryAction={onComposerPrimaryAction}
            />
          </div>
        </section>
        {isVisibleRightPanelOpen ? (
          <>
            <RightSidebarResizeHandle
              width={rightPanelWidth}
              onPointerDown={startRightPanelResize}
              onKeyDown={resizeRightPanelByKeyboard}
            />
            <aside className="replay-review-side-panel-slot" aria-label="Right review workspace">
              <div className="replay-source-header">
                <div className="replay-source-title" title={activeEvidenceSource.document.filename}>
                  {activeEvidenceSource.document.filename}
                </div>
                <div className="replay-source-subtitle" title={activeEvidenceSource.evidenceUri}>
                  {activeEvidenceSource.label}
                </div>
                <Button type="button" variant="ghost" size="icon" aria-label="Close document review" title="Close document review" onClick={() => setClosedReviewOpenKey(activeEvidenceSource.openKey)}>
                  <X className="h-4 w-4" aria-hidden="true" />
                </Button>
              </div>
              <div className="replay-review-side-panel-body">
                <QaEvidenceSourceFrame source={activeEvidenceSource} />
              </div>
            </aside>
          </>
        ) : null}
      </div>
    </section>
  );
}

const QaComposer = React.memo(function QaComposer({
  composerValue,
  isRunning,
  onComposerChange,
  onComposerKeyDown,
  onSubmitQuestion,
  onComposerPrimaryAction,
}: {
  composerValue: string;
  isRunning: boolean;
  onComposerChange: (value: string) => void;
  onComposerKeyDown: (event: React.KeyboardEvent<HTMLTextAreaElement>) => void;
  onSubmitQuestion: () => void;
  onComposerPrimaryAction: () => void;
}) {
  return (
    <form
      className="replay-agent-composer"
      aria-label="QA composer"
      onSubmit={(event) => {
        event.preventDefault();
        void onSubmitQuestion();
      }}
    >
      <div className="replay-agent-composer-balance-row">
        <div className="replay-agent-composer-frame">
          <span className="replay-agent-balance-spacer" data-agent-balance-spacer="left" data-active="true" aria-hidden="true" />
          <div className="replay-agent-composer-readable-column">
            <textarea
              aria-label="QA question input"
              value={composerValue}
              onChange={(event) => onComposerChange(event.currentTarget.value)}
              onKeyDown={onComposerKeyDown}
              placeholder="Ask a follow-up question"
              className="replay-agent-composer-input"
            />
            <div className="replay-agent-composer-actions">
              <Button type="button" variant="ghost" size="icon" aria-label="Add file" disabled>
                <Plus className="h-4 w-4" aria-hidden="true" />
              </Button>
              <Button
                type="button"
                size="icon"
                aria-label="Submit or pause answer"
                title="Submit or pause answer"
                onClick={onComposerPrimaryAction}
              >
                <span className="replay-agent-composer-action-icon-shell" aria-hidden="true">
                  <SendHorizonal className="replay-agent-composer-action-icon h-4 w-4" data-visible={isRunning ? "false" : "true"} aria-hidden="true" />
                  <Pause className="replay-agent-composer-action-icon h-4 w-4" data-visible={isRunning ? "true" : "false"} aria-hidden="true" />
                </span>
              </Button>
            </div>
          </div>
          <span className="replay-agent-balance-spacer" data-agent-balance-spacer="right" data-active="true" aria-hidden="true" />
        </div>
      </div>
    </form>
  );
});

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
        <Link href="/" className="replay-new-task-link" aria-label="New task">
          <Plus className="h-4 w-4" aria-hidden="true" />
          <span>New task</span>
        </Link>
      </div>
      <nav className="replay-task-list" aria-label="Recent tasks">
        {tasks.length > 0 ? (
          tasks.map((task) => (
            <Link
              key={task.task_id}
              href={`/tasks/${task.task_id}`}
              className={task.task_id === activeTaskId ? "replay-task-item is-active" : "replay-task-item"}
            >
              <span className="replay-task-id">{task.task_id}</span>
              <span className="replay-task-meta">
                {isTaskRunning(task) ? <Clock3 className="home-task-inline-icon" aria-hidden="true" /> : <CheckCircle2 className="home-task-inline-icon" aria-hidden="true" />}
                {task.status} / {task.stage}
              </span>
              {task.error_message ? <span className="replay-task-error">{task.error_message}</span> : null}
            </Link>
          ))
        ) : (
          <p className="replay-task-empty">No recent tasks.</p>
        )}
      </nav>
    </div>
  );
}

function QaEvidenceSourceFrame({ source }: { source: ActiveEvidenceSource }) {
  const sourceFrameRef = React.useRef<HTMLIFrameElement | null>(null);
  const sourceHtml = React.useMemo(
    () => renderQaSourceHtml(source.document.display_html),
    [source.document.display_html]
  );

  const applyCurrentEvidenceAndScroll = React.useCallback(() => {
    const frame = sourceFrameRef.current;
    const doc = frame?.contentDocument;
    if (!doc) {
      return;
    }
    applyQaSourceEvidenceMarker(doc, source.sourceSelectors, source.inlineSelector, source.headingText);
    const target = doc.querySelector<HTMLElement>("[data-current-evidence='true']");
    if (target && typeof target.scrollIntoView === "function") {
      target.scrollIntoView({ behavior: "smooth", block: "center", inline: "nearest" });
    }
  }, [source.headingText, source.inlineSelector, source.sourceSelectors]);

  React.useEffect(() => {
    applyCurrentEvidenceAndScroll();
  }, [applyCurrentEvidenceAndScroll]);

  return (
    <iframe
      title="Source document"
      className="replay-source-document replay-source-frame"
      srcDoc={sourceHtml}
      ref={sourceFrameRef}
      onLoad={applyCurrentEvidenceAndScroll}
      referrerPolicy="no-referrer"
    />
  );
}

function QaStreamRow({ item, onOpenEvidence }: { item: QaStreamItem; onOpenEvidence: (uri: string, label: string) => void }) {
  if (item.kind === "message") {
    return (
      <div className={`replay-agent-turn qa-message-turn is-${item.role}`}>
        <div className="qa-message-bubble">
          <MarkdownEvidence markdown={item.content} className="replay-agent-reason-text" onOpenEvidence={onOpenEvidence} />
        </div>
      </div>
    );
  }
  if (item.kind === "tool-group") {
    return <QaToolGroup item={item} onOpenEvidence={onOpenEvidence} />;
  }
  if (item.kind === "tool") {
    return (
      <div className="replay-agent-turn qa-tool-turn">
        <QaToolLine item={item} onOpenEvidence={onOpenEvidence} />
      </div>
    );
  }
  if (item.kind === "thinking") {
    return (
      <div className="replay-agent-turn qa-thinking-turn" aria-label="Assistant is thinking">
        <div className="qa-thinking-bubble">
          <span>Thinking</span>
          <span className="qa-thinking-bounce" aria-hidden="true">
            <span />
            <span />
            <span />
          </span>
        </div>
      </div>
    );
  }
  return (
    <div className="replay-agent-turn qa-status-turn">
      <div className="replay-agent-empty">{item.label}</div>
    </div>
  );
}

function QaToolGroup({ item, onOpenEvidence }: { item: Extract<QaStreamItem, { kind: "tool-group" }>; onOpenEvidence: (uri: string, label: string) => void }) {
  const [isExpanded, setIsExpanded] = React.useState(false);
  return (
    <div className="replay-agent-turn qa-tool-turn">
      <div className={isExpanded ? "replay-agent-tool-group is-expanded" : "replay-agent-tool-group is-collapsed"} role="group" aria-label="Tool activity">
        <button
          type="button"
          className="replay-agent-tool-group-toggle"
          aria-expanded={isExpanded}
          aria-label={`${isExpanded ? "Collapse" : "Expand"} tool activity`}
          onClick={() => setIsExpanded((current) => !current)}
        >
          <FileSearch className="replay-agent-tool-group-icon" aria-hidden="true" />
          <span className="replay-agent-tool-group-summary">{summarizeQaToolGroup(item.items)}</span>
          <ChevronRight className="replay-agent-tool-group-chevron" aria-hidden="true" />
        </button>
        {isExpanded ? (
          <div className="replay-agent-tool-group-lines">
            {item.items.map((tool) => (
              <QaToolLine key={`${tool.seq}-${tool.toolName}`} item={tool} onOpenEvidence={onOpenEvidence} />
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function QaToolLine({ item, onOpenEvidence }: { item: Extract<QaStreamItem, { kind: "tool" }>; onOpenEvidence?: (uri: string, label: string) => void }) {
  if (item.evidenceUri && onOpenEvidence) {
    return (
      <button
        type="button"
        className="replay-agent-tool-line"
        aria-label={`tool ${item.toolName}`}
        onClick={() => onOpenEvidence(item.evidenceUri ?? "", item.label)}
      >
        <QaToolIcon toolName={item.toolName} />
        <span className="replay-agent-tool-summary">{item.label}</span>
      </button>
    );
  }
  return (
    <div className="replay-agent-tool-line" aria-label={`tool ${item.toolName}`}>
      <QaToolIcon toolName={item.toolName} />
      <span className="replay-agent-tool-summary">{item.label}</span>
    </div>
  );
}

function buildQaStreamItems(events: TaskEvent[]): QaStreamItem[] {
  const rawItems = events
    .map(eventToStreamItem)
    .filter((item): item is QaStreamItem => item !== null)
    .sort((left, right) => left.seq - right.seq);
  const items: QaStreamItem[] = [];
  let pendingTools: Extract<QaStreamItem, { kind: "tool" }>[] = [];
  const flushPendingTools = () => {
    if (pendingTools.length === 0) {
      return;
    }
    if (pendingTools.length === 1) {
      items.push(pendingTools[0]);
    } else {
      const firstTool = pendingTools[0];
      items.push({
        kind: "tool-group",
        groupId: `tool-group-${firstTool.turnId ?? "no-turn"}-${firstTool.seq}`,
        seq: firstTool.seq,
        turnId: firstTool.turnId,
        items: pendingTools,
      });
    }
    pendingTools = [];
  };

  for (const item of rawItems) {
    if (item.kind === "tool") {
      pendingTools.push(item);
      continue;
    }
    flushPendingTools();
    items.push(item);
  }
  flushPendingTools();
  return items;
}

function withPendingThinkingItem(items: QaStreamItem[], isRunning: boolean): QaStreamItem[] {
  if (!isRunning) {
    return items;
  }
  const lastItem = items.at(-1);
  if (!lastItem) {
    return [{ kind: "thinking", seq: 0.2, turnId: null }];
  }
  if (lastItem.kind === "message" && lastItem.role === "user") {
    return [
      ...items,
      {
        kind: "thinking",
        seq: lastItem.seq + 0.01,
        turnId: lastItem.turnId,
      },
    ];
  }
  return items;
}

function eventToStreamItem(event: TaskEvent): QaStreamItem | null {
  const payload = readObject(event.payload) ?? {};
  if (event.type === "message.created") {
    const role = readString(payload.role);
    const content = readString(payload.content).trim();
    if (!content || (role !== "user" && role !== "assistant")) {
      return null;
    }
    return { kind: "message", seq: event.seq, turnId: event.turn_id ?? null, role, content };
  }
  if (event.type === "agent.event") {
    const payloadType = readString(payload.type);
    if (payloadType === "model_message") {
      const content = readString(payload.content).trim();
      if (!content) {
        return null;
      }
      return { kind: "message", seq: event.seq, turnId: event.turn_id ?? null, role: "assistant", content };
    }
    if (payloadType === "tool_completed" || payloadType === "tool_failed") {
      const toolName = readString(payload.tool) || readString(payload.tool_name) || "tool";
      return {
        kind: "tool",
        seq: event.seq,
        turnId: event.turn_id ?? null,
        toolName,
        label: formatToolLabel(toolName, payload),
        evidenceUri: getToolEvidenceUri(toolName, payload),
        ok: payloadType !== "tool_failed",
      };
    }
  }
  if (event.type === "turn.cancel_requested") {
    return { kind: "status", seq: event.seq, turnId: event.turn_id ?? null, label: "Cancel requested" };
  }
  if (event.type === "turn.cancelled") {
    return { kind: "status", seq: event.seq, turnId: event.turn_id ?? null, label: "Cancelled" };
  }
  if (event.type === "turn.failed") {
    return { kind: "status", seq: event.seq, turnId: event.turn_id ?? null, label: readString(payload.error_message) || "Turn failed" };
  }
  return null;
}

function appendTaskEvent(current: TaskEvent[], event: TaskEvent): TaskEvent[] {
  if (current.some((item) => item.seq === event.seq)) {
    return current;
  }
  return [...current, event].sort((left, right) => left.seq - right.seq);
}

function mergeVisibleEvents(events: TaskEvent[], optimisticEvents: TaskEvent[]): TaskEvent[] {
  const mergedEvents: TaskEvent[] = [];
  for (const event of [...events, ...optimisticEvents].sort((left, right) => left.seq - right.seq)) {
    if (mergedEvents.some((current) => current.seq === event.seq)) {
      continue;
    }
    const sameMessageIndex = mergedEvents.findIndex((current) => isSameMessageEvent(current, event));
    if (sameMessageIndex >= 0 && shouldMergeSameMessageEvent(mergedEvents[sameMessageIndex], event)) {
      if (isOptimisticMessageEvent(mergedEvents[sameMessageIndex]) && !isOptimisticMessageEvent(event)) {
        mergedEvents[sameMessageIndex] = event;
      }
      continue;
    }
    mergedEvents.push(event);
  }
  return mergedEvents;
}

function createOptimisticUserEvent({
  taskId,
  content,
  afterSeq,
}: {
  taskId: string;
  content: string;
  afterSeq: number;
}): TaskEvent {
  return {
    seq: afterSeq + 0.1,
    task_id: taskId,
    turn_id: `optimistic-${Date.now()}`,
    type: "message.created",
    status: "running",
    stage: "answering",
    payload: { role: "user", content },
    created_at: new Date().toISOString(),
  };
}

function isSameMessageEvent(left: TaskEvent, right: TaskEvent): boolean {
  if (left.type !== "message.created" || right.type !== "message.created") {
    return false;
  }
  const leftPayload = readObject(left.payload) ?? {};
  const rightPayload = readObject(right.payload) ?? {};
  return readString(leftPayload.role) === readString(rightPayload.role) && readString(leftPayload.content) === readString(rightPayload.content);
}

function shouldMergeSameMessageEvent(left: TaskEvent, right: TaskEvent): boolean {
  return isOptimisticMessageEvent(left) && !isOptimisticMessageEvent(right);
}

function isOptimisticMessageEvent(event: TaskEvent): boolean {
  return event.type === "message.created" && typeof event.turn_id === "string" && event.turn_id.startsWith("optimistic-");
}

function streamItemKey(item: QaStreamItem): string {
  if (item.kind === "tool-group") {
    return `${item.kind}-${item.groupId}`;
  }
  return `${item.kind}-${item.seq}`;
}

function applyEventToSummary(summary: TaskSummary, event: TaskEvent): TaskSummary {
  const next: TaskSummary = {
    ...summary,
    status: event.status as TaskSummary["status"],
    stage: event.stage as TaskSummary["stage"],
    stream: {
      state: isTerminalTurnEvent(event) || event.status === "ready" ? "idle" : "running",
      last_event_seq: event.seq,
    },
  };
  if (isSourceIndexedEvent(event)) {
    next.source_selectors = {
      ...(summary.source_selectors ?? {}),
      ...sourceSelectorsFromSourceIndexedEvent(event),
    };
  }
  if (event.type === "turn.started" || event.type === "turn.created") {
    next.active_turn_id = event.turn_id ?? summary.active_turn_id ?? null;
  }
  if (isTerminalTurnEvent(event)) {
    next.active_turn_id = null;
    next.status = event.status === "failed" ? "failed" : "ready";
    next.stage = "ready";
  }
  return next;
}

function shouldSubmitComposerOnKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>): boolean {
  return event.key === "Enter" && !event.shiftKey && !event.altKey && !event.ctrlKey && !event.metaKey && !event.nativeEvent.isComposing;
}

function isTerminalTurnEvent(event: TaskEvent): boolean {
  return event.type === "turn.completed" || event.type === "turn.cancelled" || event.type === "turn.failed";
}

function isSourceIndexedEvent(event: TaskEvent): boolean {
  const payload = readObject(event.payload) ?? {};
  return event.type === "agent.event" && readString(payload.type) === "source_indexed";
}

function sourceSelectorsFromSourceIndexedEvent(event: TaskEvent): Record<string, string> {
  const payload = readObject(event.payload) ?? {};
  const result = readObject(payload.result) ?? {};
  const sourceSelectors = readObject(result.source_selectors) ?? {};
  return Object.fromEntries(
    Object.entries(sourceSelectors)
      .filter((entry): entry is [string, string] => typeof entry[1] === "string")
      .map(([key, value]) => [String(key), value])
  );
}

function isTaskRunning(summary?: Pick<TaskSummary, "status" | "stream" | "active_turn_id"> | null): boolean {
  return Boolean(summary?.active_turn_id || summary?.status === "running" || summary?.stream?.state === "running");
}

const QA_STREAM_BOTTOM_THRESHOLD_PX = 80;

function isElementNearBottom(element: HTMLElement): boolean {
  return element.scrollHeight - element.scrollTop - element.clientHeight <= QA_STREAM_BOTTOM_THRESHOLD_PX;
}

function formatToolLabel(toolName: string, payload: Record<string, unknown>): string {
  const args = readObject(payload.args) ?? {};
  const query = readString(args.query);
  if (toolName === "grep") {
    return query ? `Searched ${query}` : "Searched document";
  }
  if (toolName === "tree") {
    return "Viewed outline";
  }
  if (toolName === "read") {
    return `Read ${getToolTargetKind(payload, "passage")}`;
  }
  if (toolName === "inspect") {
    return `Inspected ${getToolTargetKind(payload, "evidence")}`;
  }
  return `Ran ${toolName}`;
}

function getToolEvidenceUri(toolName: string, payload: Record<string, unknown>): string | null {
  if (toolName !== "read" && toolName !== "inspect") {
    return null;
  }
  const args = readObject(payload.args) ?? {};
  const result = readObject(payload.result) ?? {};
  const locator =
    readString(args.locator) ||
    readString(args.path_id) ||
    readString(args.path) ||
    readString(result.locator) ||
    readString(result.path_id) ||
    readString(result.path);
  if (!locator) {
    return null;
  }
  return locator.startsWith("evidence://") ? locator : `evidence://${locator}`;
}

function getToolTargetKind(payload: Record<string, unknown>, fallback: string): string {
  const args = readObject(payload.args) ?? {};
  const result = readObject(payload.result) ?? {};
  const kind =
    readString(result.kind) ||
    readString(result.block_kind) ||
    readString(args.kind) ||
    readString(args.block_kind) ||
    readString(payload.kind);
  return formatToolTargetKind(kind || fallback);
}

function formatToolTargetKind(kind: string): string {
  const normalized = kind.toLowerCase().replace(/[-\s]+/g, "_");
  if (normalized === "table_row" || normalized === "row") {
    return "table row";
  }
  if (normalized === "list_item" || normalized === "item") {
    return "list item";
  }
  if (normalized === "heading" || normalized === "header") {
    return "heading";
  }
  if (normalized === "paragraph" || normalized === "section" || normalized === "list" || normalized === "table" || normalized === "document" || normalized === "outline" || normalized === "evidence" || normalized === "passage") {
    return normalized;
  }
  return "evidence";
}

function summarizeQaToolGroup(items: Extract<QaStreamItem, { kind: "tool" }>[]): string {
  const counts = items.reduce(
    (summary, item) => {
      if (item.toolName === "grep") {
        summary.searches += 1;
      } else if (item.toolName === "read") {
        summary.reads += 1;
      } else if (item.toolName === "inspect") {
        summary.inspects += 1;
      } else if (item.toolName === "tree") {
        summary.outlines += 1;
      } else {
        summary.other += 1;
      }
      return summary;
    },
    { inspects: 0, outlines: 0, other: 0, reads: 0, searches: 0 }
  );
  const parts: string[] = [];
  if (counts.reads > 0) {
    parts.push(`read ${formatCount(counts.reads, "passage")}`);
  }
  if (counts.inspects > 0) {
    parts.push(`inspected ${formatCount(counts.inspects, "evidence", "evidence")}`);
  }
  if (counts.outlines > 0) {
    parts.push(`viewed ${formatCount(counts.outlines, "outline")}`);
  }
  if (counts.searches > 0) {
    parts.push(formatCount(counts.searches, "search", "searches"));
  }
  if (counts.other > 0) {
    parts.push(`ran ${formatCount(counts.other, "tool")}`);
  }
  return capitalizeFirst(parts.join(", "));
}

function formatCount(count: number, singular: string, plural = `${singular}s`): string {
  return `${count} ${count === 1 ? singular : plural}`;
}

function capitalizeFirst(value: string): string {
  return value ? value.charAt(0).toUpperCase() + value.slice(1) : value;
}

function QaToolIcon({ toolName }: { toolName: string }) {
  if (toolName === "grep") {
    return <Search className="replay-agent-tool-icon" aria-hidden="true" />;
  }
  if (toolName === "inspect") {
    return <Eye className="replay-agent-tool-icon" aria-hidden="true" />;
  }
  if (toolName === "read") {
    return <BookOpenText className="replay-agent-tool-icon" aria-hidden="true" />;
  }
  if (toolName === "tree") {
    return <FileSearch className="replay-agent-tool-icon" aria-hidden="true" />;
  }
  return <Wrench className="replay-agent-tool-icon" aria-hidden="true" />;
}

function StatusBadge({ status }: { status: TaskSummary["status"] }) {
  if (status === "ready") {
    return <Badge variant="success">{status}</Badge>;
  }
  if (status === "running" || status === "processing") {
    return <Badge variant="warning">{status}</Badge>;
  }
  if (status === "failed") {
    return <Badge variant="destructive">{status}</Badge>;
  }
  return <Badge variant="secondary">{status}</Badge>;
}

function qaStageColumns(isLeftPanelOpen: boolean, isRightPanelOpen: boolean): string {
  const leftColumns = isLeftPanelOpen ? "var(--replay-left-panel-width) 10px " : "";
  const rightColumns = isRightPanelOpen ? " 10px var(--replay-right-panel-width)" : "";
  return `${leftColumns}minmax(0, 1fr)${rightColumns}`;
}

function getAgentBalanceSide(isLeftPanelOpen: boolean, isRightPanelOpen: boolean): "left" | "right" | "both" | "none" {
  if (isLeftPanelOpen && isRightPanelOpen) {
    return "both";
  }
  if (isLeftPanelOpen) {
    return "left";
  }
  if (isRightPanelOpen) {
    return "right";
  }
  return "none";
}

function findEvidenceSource(summary: TaskSummary | null | undefined, uri: string, label: string): ActiveEvidenceSource | null {
  const documents = summary?.documents ?? [];
  if (documents.length === 0) {
    return null;
  }
  const evidenceId = getEvidenceIdFromUri(uri);
  const sourceSelectors = findSourceSelectors(summary?.source_selectors ?? {}, evidenceId);
  const sourceSelector = sourceSelectors[0] ?? "";
  if (!sourceSelector) {
    return null;
  }
  const document = documents[getEvidenceDocumentIndex(evidenceId, documents)] ?? documents[0];
  if (!document) {
    return null;
  }
  return { document, evidenceUri: uri, label, openKey: 0, sourceSelector, sourceSelectors, inlineSelector: getEvidenceInlineSelector(uri), headingText: label };
}

function findSourceSelectors(sourceSelectors: Record<string, string>, evidenceId: string): string[] {
  const rangeSelectors = findRangeSourceSelectors(sourceSelectors, evidenceId);
  if (rangeSelectors.length > 0) {
    return rangeSelectors;
  }
  const sourceSelector = findSourceSelector(sourceSelectors, evidenceId);
  return sourceSelector ? [sourceSelector] : [];
}

function findSourceSelector(sourceSelectors: Record<string, string>, evidenceId: string): string {
  for (const key of getEvidenceLookupKeys(evidenceId)) {
    const sourceSelector = sourceSelectors[key];
    if (sourceSelector) {
      return sourceSelector;
    }
  }
  const headerSelector = stripEvidenceScheme(evidenceId).split(/[/#]/)[0] ?? "";
  return isVirtualPathId(headerSelector) && hasDescendantSourceSelector(sourceSelectors, headerSelector) ? headerSelector : "";
}

function hasDescendantSourceSelector(sourceSelectors: Record<string, string>, parentPathId: string): boolean {
  return Object.keys(sourceSelectors).some((pathId) => pathId.startsWith(`${parentPathId}.`));
}

function getEvidenceLookupKeys(evidenceId: string): string[] {
  const withoutScheme = stripEvidenceScheme(evidenceId);
  const withoutInlineSelector = withoutScheme.split("/")[0] ?? withoutScheme;
  const withoutHashSelector = withoutScheme.split("#")[0] ?? withoutScheme;
  return [...new Set([evidenceId, withoutScheme, withoutInlineSelector, withoutHashSelector].filter(Boolean))];
}

function getEvidenceIdFromUri(uri: string): string {
  return stripEvidenceScheme(uri).split("#")[0] ?? "";
}

function getEvidenceInlineSelector(uri: string): string {
  return (stripEvidenceScheme(uri).split("/")[1] ?? "").split("#")[0] ?? "";
}

function stripEvidenceScheme(value: string): string {
  return value.replace(/^evidence:\/\//, "");
}

function isVirtualPathId(value: string): boolean {
  return /^\d+(?:\.\d+)+$/.test(value);
}

function findRangeSourceSelectors(sourceSelectors: Record<string, string>, evidenceId: string): string[] {
  const range = parseEvidenceRangeId(evidenceId);
  if (!range) {
    return [];
  }
  const pathIds = getEvidenceRangePathIds(sourceSelectors, range);
  const selectors: string[] = [];
  for (const pathId of pathIds) {
    const sourceSelector = sourceSelectors[pathId];
    if (typeof sourceSelector !== "string") {
      continue;
    }
    const normalizedSelector = normalizeQaSourceSelector(sourceSelector);
    if (normalizedSelector && !selectors.includes(normalizedSelector)) {
      selectors.push(normalizedSelector);
    }
  }
  return selectors;
}

function parseEvidenceRangeId(evidenceId: string): { start: string; end: string } | null {
  const withoutScheme = stripEvidenceScheme(evidenceId).split("#")[0] ?? "";
  const parts = withoutScheme.split("/").filter(Boolean);
  if (parts.length !== 3 || parts[0] !== "range") {
    return null;
  }
  const [, start, end] = parts;
  if (!isVirtualPathId(start) || !isVirtualPathId(end)) {
    return null;
  }
  return { start, end };
}

function getEvidenceRangePathIds(sourceSelectors: Record<string, string>, range: { start: string; end: string }): string[] {
  const [rangeStart, rangeEnd] = compareEvidencePathIds(range.start, range.end) <= 0 ? [range.start, range.end] : [range.end, range.start];
  const rangePathIds = Object.keys(sourceSelectors)
    .filter((pathId) => isVirtualPathId(pathId) && isEvidencePathIdInsideRange(pathId, rangeStart, rangeEnd))
    .sort(compareEvidencePathIds);
  return rangePathIds.length > 0 ? rangePathIds : [rangeStart];
}

function isEvidencePathIdInsideRange(pathId: string, rangeStart: string, rangeEnd: string): boolean {
  const startSegments = rangeStart.split(".");
  const endSegments = rangeEnd.split(".");
  const pathSegments = pathId.split(".");
  if (startSegments.length !== endSegments.length || pathSegments.length < startSegments.length) {
    return pathId === rangeStart;
  }
  const startParentPath = startSegments.slice(0, -1).join(".");
  const endParentPath = endSegments.slice(0, -1).join(".");
  const pathParentPrefix = pathSegments.slice(0, startSegments.length - 1).join(".");
  const pathPrefix = pathSegments.slice(0, startSegments.length).join(".");
  if (startParentPath !== endParentPath || pathParentPrefix !== startParentPath) {
    return false;
  }
  return compareEvidencePathIds(pathPrefix, rangeStart) >= 0 && compareEvidencePathIds(pathPrefix, rangeEnd) <= 0;
}

function compareEvidencePathIds(left: string, right: string): number {
  const leftParts = stripEvidenceScheme(left).split(".").map((part) => Number.parseInt(part, 10));
  const rightParts = stripEvidenceScheme(right).split(".").map((part) => Number.parseInt(part, 10));
  const maxLength = Math.max(leftParts.length, rightParts.length);
  for (let index = 0; index < maxLength; index += 1) {
    const leftPart = leftParts[index] ?? 0;
    const rightPart = rightParts[index] ?? 0;
    if (leftPart !== rightPart) {
      return leftPart - rightPart;
    }
  }
  return 0;
}

function getEvidenceDocumentIndex(evidenceId: string, documents: TaskSourceDocument[]): number {
  const firstPart = stripEvidenceScheme(evidenceId).split(/[./]/)[0] ?? "";
  const parsed = Number.parseInt(firstPart, 10);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return 0;
  }
  return Math.min(parsed - 1, Math.max(documents.length - 1, 0));
}

function renderQaSourceHtml(displayHtml: string): string {
  const sanitizedHtml = stripExecutableSourceHtml(displayHtml || "<p>No source document is available.</p>");
  return wrapQaSourceHtml(sanitizedHtml);
}

function applyQaSourceEvidenceMarker(doc: Document, sourceSelectors: string[], inlineSelector: string, headingText: string): void {
  for (const element of Array.from(doc.querySelectorAll<HTMLElement>("[data-current-evidence='true']"))) {
    element.removeAttribute("data-current-evidence");
    element.classList.remove("is-current-evidence");
  }
  for (const sourceSelector of sourceSelectors) {
    const target = findQaSourceEvidenceTarget(doc, sourceSelector, inlineSelector, headingText);
    if (!target) {
      continue;
    }
    target.classList.add("is-current-evidence");
    target.setAttribute("data-current-evidence", "true");
  }
}

function findQaSourceEvidenceTarget(doc: Document, sourceSelector: string, inlineSelector: string, headingText: string): HTMLElement | null {
  const normalizedSelector = normalizeQaSourceSelector(sourceSelector);
  if (!normalizedSelector) {
    return null;
  }
  for (const candidate of inlineQaSourceSelectorCandidates(normalizedSelector, inlineSelector)) {
    const target = findQaSourceElementByIdOrDataElementId(doc, candidate);
    if (target) {
      return target;
    }
  }
  return findQaSourceElementByIdOrDataElementId(doc, normalizedSelector) ?? findQaHeaderElementByText(doc, headingText);
}

function findQaSourceElementByIdOrDataElementId(doc: Document, selector: string): HTMLElement | null {
  const byId = doc.getElementById(selector);
  if (byId) {
    return byId;
  }
  for (const element of Array.from(doc.querySelectorAll<HTMLElement>("[data-element-id]"))) {
    if (element.getAttribute("data-element-id") === selector) {
      return element;
    }
  }
  return null;
}

function findQaHeaderElementByText(doc: Document, headingText: string): HTMLElement | null {
  const normalizedHeadingText = normalizeQaHeaderText(headingText);
  if (!normalizedHeadingText) {
    return null;
  }
  for (const element of Array.from(doc.querySelectorAll<HTMLElement>("h1,h2,h3,h4,h5,h6"))) {
    if (normalizeQaHeaderText(element.textContent ?? "") === normalizedHeadingText) {
      return element;
    }
  }
  return null;
}

function normalizeQaHeaderText(value: string): string {
  return value.replace(/\s+/g, " ").trim().toLocaleLowerCase();
}

function inlineQaSourceSelectorCandidates(sourceSelector: string, inlineSelector: string): string[] {
  const normalizedInlineSelector = inlineSelector.trim().toUpperCase();
  const match = /^([IR])(\d+)$/.exec(normalizedInlineSelector);
  if (!match) {
    return [];
  }
  const inlineIndex = Number.parseInt(match[2], 10);
  if (!Number.isFinite(inlineIndex) || inlineIndex <= 0) {
    return [];
  }
  if (match[1] === "I") {
    return [`${sourceSelector}_item_${String(inlineIndex - 1).padStart(3, "0")}`];
  }
  return [
    `${sourceSelector}_tr_${String(inlineIndex).padStart(3, "0")}`,
    `${sourceSelector}_tr_${String(inlineIndex - 1).padStart(3, "0")}`,
  ];
}

function normalizeQaSourceSelector(sourceSelector: string): string {
  return sourceSelector.trim().replace(/^#/, "");
}

function wrapQaSourceHtml(displayHtml: string): string {
  const style = `<style>
html, body { margin: 0; padding: 0; background: #fff; color: #171717; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; line-height: 1.55; }
main { max-width: 980px !important; margin: 0 auto !important; padding: 24px !important; }
.page { background: transparent !important; margin: 0 0 20px !important; padding: 0 !important; box-shadow: none !important; }
img, svg, canvas, video { max-width: 100% !important; height: auto !important; }
p, li, td, th, pre, code { max-width: 100% !important; white-space: pre-wrap !important; overflow-wrap: anywhere !important; }
.is-current-evidence, [data-current-evidence="true"] { border-radius: 6px !important; background: rgba(51, 156, 255, 0.18) !important; outline: 2px solid rgba(51, 156, 255, 0.55) !important; outline-offset: 2px !important; scroll-margin: 48px !important; }
</style>`;
  const html = /<html\b/i.test(displayHtml)
    ? displayHtml
    : `<!doctype html><html><head><meta charset="utf-8"></head><body>${displayHtml}</body></html>`;
  if (/<\/head>/i.test(html)) {
    return html.replace(/<\/head>/i, `${style}</head>`);
  }
  if (/<head\b[^>]*>/i.test(html)) {
    return html.replace(/<head\b[^>]*>/i, (match) => `${match}${style}`);
  }
  return html.replace(/<html\b[^>]*>/i, (match) => `${match}<head><meta charset="utf-8">${style}</head>`);
}

function stripExecutableSourceHtml(displayHtml: string): string {
  return displayHtml.replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, "");
}

function readObject(value: unknown): Record<string, unknown> | null {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  return null;
}

function readString(value: unknown): string {
  return typeof value === "string" ? value : "";
}
