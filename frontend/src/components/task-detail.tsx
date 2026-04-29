"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowLeft, Loader2, RefreshCw, ShieldCheck } from "lucide-react";
import { toast } from "sonner";

import {
  loadTaskDetail as defaultLoadTaskDetail,
  submitTaskReview as defaultSubmitReview
} from "@/lib/api";
import { stringifyValue } from "@/lib/json";
import { updateRecentTask } from "@/lib/task-store";
import type {
  AgentTraceRecord,
  AgentProcess,
  AgentProcessStep,
  EvidenceBlock,
  ReviewSubmitPayload,
  TaskDetailData,
  TaskSummary,
  TraceAction,
  TraceStep
} from "@/lib/types";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { MarkdownEvidence } from "@/components/markdown-evidence";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";

type FieldLabelMap = Record<string, string>;

export interface TaskDetailProps {
  taskId: string;
  initialSummary?: TaskSummary;
  loadTaskDetail?: (taskId: string) => Promise<TaskDetailData>;
  submitReview?: (taskId: string, payload: ReviewSubmitPayload) => Promise<TaskSummary>;
}

export function TaskDetail({
  taskId,
  initialSummary,
  loadTaskDetail = defaultLoadTaskDetail,
  submitReview = defaultSubmitReview
}: TaskDetailProps) {
  const [detail, setDetail] = React.useState<TaskDetailData | null>(
    initialSummary
      ? { summary: initialSummary, result: null, trace: null, review: null, audit: null }
      : null
  );
  const [reviewValues, setReviewValues] = React.useState<Record<string, string>>({});
  const [comment, setComment] = React.useState("");
  const [isLoading, setIsLoading] = React.useState(true);
  const [isSubmitting, setIsSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const refresh = React.useCallback(async () => {
    try {
      const loaded = await loadTaskDetail(taskId);
      setDetail(loaded);
      updateRecentTask(loaded.summary);
      setReviewValues((current) => {
        if (!loaded.review) {
          return current;
        }
        const next = { ...current };
        for (const field of loaded.review.fields) {
          if (!(field.field_name in next)) {
            next[field.field_name] = stringifyValue(field.agent_value);
          }
        }
        return next;
      });
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "加载任务失败");
    } finally {
      setIsLoading(false);
    }
  }, [loadTaskDetail, taskId]);

  React.useEffect(() => {
    // 初次进入详情页需要从 backend 同步任务快照。
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refresh();
  }, [refresh]);

  function handleManualRefresh() {
    setIsLoading(true);
    setError(null);
    void refresh();
  }

  async function handleSubmitReview() {
    if (!detail?.review) {
      return;
    }
    const fields = detail.review.fields
      .filter((field) => field.needs_review)
      .map((field) => ({
        field_name: field.field_name,
        review_value: reviewValues[field.field_name] ?? ""
      }));
    const payload: ReviewSubmitPayload = {
      decision: "revise_and_approve",
      fields,
      comment,
      reviewer: "frontend"
    };

    setIsSubmitting(true);
    setError(null);
    try {
      await submitReview(taskId, payload);
      toast.success("复核已提交");
      await refresh();
    } catch (submitError) {
      const message = submitError instanceof Error ? submitError.message : "提交复核失败";
      setError(message);
      toast.error("提交复核失败", { description: message });
    } finally {
      setIsSubmitting(false);
    }
  }

  const summary = detail?.summary ?? initialSummary;
  const fieldLabels = React.useMemo(() => (detail ? buildFieldLabels(detail) : {}), [detail]);

  return (
    <main className="min-h-[calc(100svh-4rem)] space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <Link
            href="/"
            className="mb-3 inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="h-4 w-4" />
            返回上传工作台
          </Link>
          <h1 className="text-3xl font-semibold tracking-normal text-foreground">{taskId}</h1>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            {summary ? <StatusBadge status={summary.status} /> : null}
            {summary ? <Badge variant="outline">{summary.stage}</Badge> : null}
            {summary?.route ? <RouteBadge route={summary.route} /> : null}
          </div>
        </div>
        <Button type="button" variant="outline" onClick={handleManualRefresh} disabled={isLoading}>
          {isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw />}
          刷新
        </Button>
      </div>

      {error ? (
        <Alert variant="destructive">
          <AlertTitle>任务加载失败</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      {isLoading && !detail ? (
        <div className="rounded-md border border-dashed p-8 text-sm text-muted-foreground">正在加载任务详情...</div>
      ) : null}

      {detail ? (
        <Tabs
          defaultValue={
            detail.review || detail.summary.status === "waiting_review" ? "review" : "result"
          }
          className="w-full"
        >
          <TabsList>
            <TabsTrigger value="result">结果</TabsTrigger>
            <TabsTrigger value="review">复核</TabsTrigger>
            <TabsTrigger value="trace">证据</TabsTrigger>
            <TabsTrigger value="audit">审计</TabsTrigger>
          </TabsList>

          <TabsContent value="result">
            <ResultTable detail={detail} fieldLabels={fieldLabels} />
          </TabsContent>

          <TabsContent value="review">
            <section className="space-y-4">
              {detail.review ? (
                <>
                  <Alert>
                    <ShieldCheck className="absolute left-4 top-4 h-4 w-4 text-primary" />
                    <AlertTitle className="pl-6">等待人工复核</AlertTitle>
                    <AlertDescription className="pl-6">
                      {detail.review.route_reason ?? "请确认需要接管的字段值和证据。"}
                    </AlertDescription>
                  </Alert>
                  <div className="space-y-5">
                    {detail.review.fields.map((field) => (
                      <div key={field.field_name} className="rounded-md border p-4">
                        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                          <div>
                            <h2 className="font-medium">
                              {getFieldLabel(fieldLabels, field.field_name, field.display_name)}
                            </h2>
                          </div>
                          {field.needs_review ? <Badge variant="warning">needs_review</Badge> : null}
                        </div>
                        <dl className="mb-4 grid gap-3 text-sm md:grid-cols-2">
                          <div>
                            <dt className="text-muted-foreground">Agent 值</dt>
                            <dd className="mt-1 font-mono">{stringifyValue(field.agent_value)}</dd>
                          </div>
                          <div>
                            <dt className="text-muted-foreground">动作</dt>
                            <dd className="mt-1 flex flex-wrap gap-2">
                              {(field.actions ?? []).map((action) => (
                                <Badge key={action} variant="outline">
                                  {action}
                                </Badge>
                              ))}
                            </dd>
                          </div>
                        </dl>
                        <EvidenceList texts={field.evidence_texts ?? []} />
                        <AgentProcessList
                          title="Agent 决策过程"
                          processes={field.agent_process ? [field.agent_process] : []}
                          fieldLabels={fieldLabels}
                        />
                        <div className="mt-4 space-y-2">
                          <Label htmlFor={`review-${field.field_name}`}>
                            {getFieldLabel(fieldLabels, field.field_name, field.display_name)} 复核值
                          </Label>
                          <Textarea
                            id={`review-${field.field_name}`}
                            value={reviewValues[field.field_name] ?? ""}
                            onChange={(event) =>
                              setReviewValues((current) => ({
                                ...current,
                                [field.field_name]: event.target.value
                              }))
                            }
                          />
                        </div>
                      </div>
                    ))}
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="review-comment">复核备注</Label>
                    <Textarea
                      id="review-comment"
                      value={comment}
                      onChange={(event) => setComment(event.target.value)}
                      className="min-h-20"
                    />
                  </div>
                  <Button type="button" onClick={() => void handleSubmitReview()} disabled={isSubmitting}>
                    {isSubmitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <ShieldCheck />}
                    提交修正并通过
                  </Button>
                </>
              ) : (
                <p className="text-sm text-muted-foreground">当前任务不需要人工复核。</p>
              )}
            </section>
          </TabsContent>

          <TabsContent value="trace">
            <TraceView detail={detail} fieldLabels={fieldLabels} />
          </TabsContent>

          <TabsContent value="audit">
            <AuditTable detail={detail} fieldLabels={fieldLabels} />
          </TabsContent>
        </Tabs>
      ) : null}
    </main>
  );
}

function ResultTable({
  detail,
  fieldLabels
}: {
  detail: TaskDetailData;
  fieldLabels: FieldLabelMap;
}) {
  const fields = detail.result?.fields ?? [];
  if (fields.length === 0) {
    return <p className="text-sm text-muted-foreground">暂无最终字段结果。</p>;
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>字段</TableHead>
          <TableHead>Agent 值</TableHead>
          <TableHead>最终值</TableHead>
          <TableHead>来源</TableHead>
          <TableHead>提交</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {fields.map((field) => (
          <TableRow key={field.field_name}>
            <TableCell>
              <div className="font-medium">
                {getFieldLabel(fieldLabels, field.field_name, field.display_name)}
              </div>
            </TableCell>
            <TableCell className="font-mono text-xs">{stringifyValue(field.agent_value)}</TableCell>
            <TableCell className="font-mono text-xs">{stringifyValue(field.final_value)}</TableCell>
            <TableCell>{field.source ?? "-"}</TableCell>
            <TableCell>{field.committed ? "已提交" : "未提交"}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function TraceView({
  detail,
  fieldLabels
}: {
  detail: TaskDetailData;
  fieldLabels: FieldLabelMap;
}) {
  const fields = detail.trace?.fields ?? [];
  const steps = detail.trace?.steps ?? [];
  const agentTrace = detail.trace?.agent_trace ?? [];
  if (fields.length === 0 && steps.length === 0 && agentTrace.length === 0) {
    return <p className="text-sm text-muted-foreground">暂无 trace 数据。</p>;
  }
  return (
    <div className="space-y-6">
      <AgentExecutionSteps steps={steps} fieldLabels={fieldLabels} />
      <AgentRawTrace records={agentTrace} />
      {fields.map((field) => (
        <section key={field.field_name} className="rounded-md border p-4">
          <h2 className="font-medium">{getFieldLabel(fieldLabels, field.field_name)}</h2>
          {field.reason ? <p className="mt-1 text-sm text-muted-foreground">{field.reason}</p> : null}
          <EvidenceList texts={field.evidence?.texts ?? []} />
          <div className="mt-3 flex flex-wrap gap-2">
            {(field.actions ?? []).map((action, index) => (
              <Badge key={`${action.action_type}-${index}`} variant="outline">
                {action.action_type ?? action.message}
              </Badge>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

function AgentRawTrace({ records }: { records: AgentTraceRecord[] }) {
  if (records.length === 0) {
    return null;
  }
  return (
    <section className="space-y-3">
      <div>
        <h2 className="text-sm font-semibold text-foreground">Agent 原始 trace</h2>
        <p className="mt-1 text-xs text-muted-foreground">
          backend 按实际调用顺序保存的 agent 请求摘要、响应和 trace payload。
        </p>
      </div>
      <div className="space-y-2">
        {records.map((record) => (
          <div key={record.id ?? `${record.sequence}-${record.agent}`} className="rounded-md border p-3 text-xs">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="outline">{record.sequence}</Badge>
                <span className="font-medium text-foreground">
                  {record.agent} / {record.stage}
                </span>
                <Badge variant={record.status === "completed" ? "success" : "secondary"}>
                  {record.status}
                </Badge>
              </div>
              <span className="text-muted-foreground">
                {formatStepTime(record.started_at)} {"->"} {formatStepTime(record.finished_at)}
              </span>
            </div>
            {record.failure_reason ? (
              <p className="mt-2 text-destructive">{record.failure_reason}</p>
            ) : null}
            <div className="mt-3 grid gap-2 lg:grid-cols-3">
              <TracePayload title="request" payload={record.request} />
              <TracePayload title="response" payload={record.response} />
              <TracePayload title="trace" payload={record.trace} />
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function TracePayload({
  title,
  payload
}: {
  title: string;
  payload?: Record<string, unknown>;
}) {
  const keys = Object.keys(payload ?? {});
  if (keys.length === 0) {
    return null;
  }
  return (
    <details className="rounded-md bg-muted px-3 py-2">
      <summary className="cursor-pointer text-muted-foreground">
        {title}: {keys.slice(0, 6).join(", ")}
      </summary>
      <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words rounded bg-background p-2 font-mono text-[11px] text-foreground">
        {JSON.stringify(payload, null, 2)}
      </pre>
    </details>
  );
}

function AgentExecutionSteps({
  steps,
  fieldLabels
}: {
  steps: TraceStep[];
  fieldLabels: FieldLabelMap;
}) {
  if (steps.length === 0) {
    return null;
  }
  return (
    <section className="space-y-3">
      <div>
        <h2 className="text-sm font-semibold text-foreground">Agent 执行过程</h2>
        <p className="mt-1 text-xs text-muted-foreground">
          按 backend 实际调用顺序展示每个 agent 阶段的输入输出摘要。
        </p>
      </div>
      <div className="space-y-3">
        {steps.map((step, index) => (
          <div key={`${step.stage}-${step.agent}-${index}`} className="rounded-md border p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant="outline">{index + 1}</Badge>
                  <h3 className="font-mono text-sm font-medium text-foreground">{step.agent}</h3>
                  <Badge variant={step.status === "completed" ? "success" : "secondary"}>
                    {step.status}
                  </Badge>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">{step.stage}</p>
              </div>
              <p className="text-xs text-muted-foreground">
                {formatStepTime(step.started_at)} {"->"} {formatStepTime(step.finished_at)}
              </p>
            </div>

            {step.failure_reason ? (
              <Alert variant="destructive" className="mt-3">
                <AlertTitle>执行失败</AlertTitle>
                <AlertDescription>{step.failure_reason}</AlertDescription>
              </Alert>
            ) : null}

            <StepSummary summary={step.summary} />
            <AgentProcessList
              title="字段决策过程"
              processes={step.field_decisions ?? []}
              fieldLabels={fieldLabels}
            />
            <StepDocuments documents={step.documents ?? []} />
            <StepRoutes routes={step.routes ?? []} fieldLabels={fieldLabels} />
          </div>
        ))}
      </div>
    </section>
  );
}

function StepSummary({ summary }: { summary?: Record<string, unknown> }) {
  if (!summary) {
    return null;
  }
  const entries = flattenSummary(summary);
  if (entries.length === 0) {
    return null;
  }
  return (
    <dl className="mt-3 grid gap-2 text-xs sm:grid-cols-2 lg:grid-cols-4">
      {entries.map(([label, value]) => (
        <div key={label} className="rounded-md bg-muted px-3 py-2">
          <dt className="text-muted-foreground">{label}</dt>
          <dd className="mt-1 font-mono text-foreground">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function StepDocuments({ documents }: { documents: NonNullable<TraceStep["documents"]> }) {
  if (documents.length === 0) {
    return null;
  }
  return (
    <div className="mt-3 overflow-x-auto rounded-md border border-border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>文件</TableHead>
            <TableHead>类型</TableHead>
            <TableHead>blocks</TableHead>
            <TableHead>warnings</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {documents.map((document) => (
            <TableRow key={document.document_id ?? document.filename}>
              <TableCell>{document.filename}</TableCell>
              <TableCell>{document.file_type ?? "-"}</TableCell>
              <TableCell>{document.block_count ?? "-"}</TableCell>
              <TableCell>{document.warning_count ?? 0}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function StepRoutes({
  routes,
  fieldLabels
}: {
  routes: NonNullable<TraceStep["routes"]>;
  fieldLabels: FieldLabelMap;
}) {
  if (routes.length === 0) {
    return null;
  }
  return (
    <div className="mt-3 space-y-2">
      {routes.map((route) => (
        <div key={route.field_name} className="rounded-md bg-muted px-3 py-2 text-xs">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-foreground">{getFieldLabel(fieldLabels, route.field_name)}</span>
            <Badge variant={route.route === "accept" ? "success" : route.route === "review" ? "warning" : "destructive"}>
              {route.route}
            </Badge>
            {route.needs_review ? <span className="text-muted-foreground">needs_review</span> : null}
          </div>
          {route.route_reason ? (
            <p className="mt-1 text-muted-foreground">{route.route_reason}</p>
          ) : null}
        </div>
      ))}
    </div>
  );
}

function flattenSummary(summary: Record<string, unknown>): Array<[string, string]> {
  const entries: Array<[string, string]> = [];
  for (const [key, value] of Object.entries(summary)) {
    if (value === null || value === undefined) {
      continue;
    }
    if (typeof value === "object" && !Array.isArray(value)) {
      for (const [nestedKey, nestedValue] of Object.entries(value as Record<string, unknown>)) {
        entries.push([`${key}.${nestedKey}`, `${nestedKey}: ${stringifyValue(nestedValue)}`]);
      }
    } else {
      entries.push([key, stringifyValue(value)]);
    }
  }
  return entries;
}

function formatStepTime(value: string | null | undefined): string {
  if (!value) {
    return "-";
  }
  return value;
}

function AuditTable({
  detail,
  fieldLabels
}: {
  detail: TaskDetailData;
  fieldLabels: FieldLabelMap;
}) {
  const commits = detail.audit?.field_commits ?? [];
  if (commits.length === 0) {
    return <p className="text-sm text-muted-foreground">暂无审计提交记录。</p>;
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>字段</TableHead>
          <TableHead>最终值</TableHead>
          <TableHead>route</TableHead>
          <TableHead>复核</TableHead>
          <TableHead>提交方</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {commits.map((commit) => (
          <React.Fragment key={`${commit.field_name}-${commit.committed_at ?? ""}`}>
            <TableRow>
              <TableCell>{getFieldLabel(fieldLabels, commit.field_name)}</TableCell>
              <TableCell className="font-mono text-xs">{stringifyValue(commit.final_value)}</TableCell>
              <TableCell>{commit.route ?? "-"}</TableCell>
              <TableCell>{commit.reviewed ? commit.review_decision ?? "reviewed" : "否"}</TableCell>
              <TableCell>{commit.committed_by ?? "-"}</TableCell>
            </TableRow>
            {commit.agent_process ? (
              <TableRow>
                <TableCell colSpan={5}>
                  <AgentProcessList
                    title="Agent 决策过程"
                    processes={[commit.agent_process]}
                    fieldLabels={fieldLabels}
                  />
                </TableCell>
              </TableRow>
            ) : null}
          </React.Fragment>
        ))}
      </TableBody>
    </Table>
  );
}

function AgentProcessList({
  title,
  processes,
  fieldLabels
}: {
  title: string;
  processes: AgentProcess[];
  fieldLabels: FieldLabelMap;
}) {
  if (processes.length === 0) {
    return null;
  }
  return (
    <div className="mt-3 space-y-2">
      <p className="text-xs font-medium text-muted-foreground">{title}</p>
      {processes.map((process) => {
        const processSteps = process.process_steps ?? [];
        return (
          <div key={process.field_name} className="rounded-md border border-dashed p-3 text-xs">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-foreground">{getFieldLabel(fieldLabels, process.field_name)}</span>
              {process.status ? <Badge variant="outline">{process.status}</Badge> : null}
            </div>
            {"value" in process ? (
              <dl className="mt-2 grid gap-2 sm:grid-cols-2">
                <div>
                  <dt className="text-muted-foreground">定案值</dt>
                  <dd className="mt-1 font-mono text-foreground">{stringifyValue(process.value)}</dd>
                </div>
                {process.evidence?.status ? (
                  <div>
                    <dt className="text-muted-foreground">证据状态</dt>
                    <dd className="mt-1 font-mono text-foreground">{process.evidence.status}</dd>
                  </div>
                ) : null}
              </dl>
            ) : null}
            {process.reason ? (
              <p className="mt-2 text-muted-foreground">{process.reason}</p>
            ) : null}
            {process.failure_reason ? (
              <p className="mt-2 text-destructive">{process.failure_reason}</p>
            ) : null}
            <ProcessStepList steps={processSteps} fieldLabels={fieldLabels} />
            {processSteps.length === 0 ? <ProcessNotes notes={process.evidence?.notes ?? []} /> : null}
            {processSteps.length === 0 ? <TraceActionList actions={process.actions ?? []} /> : null}
          </div>
        );
      })}
    </div>
  );
}

function ProcessStepList({ steps, fieldLabels }: { steps: AgentProcessStep[]; fieldLabels: FieldLabelMap }) {
  if (steps.length === 0) {
    return null;
  }
  return (
    <div className="mt-3 space-y-2">
      {steps.map((step, index) => {
        const outputFields = step.output_fields ?? [];
        return (
          <div key={`${step.stage}-${index}`} className="rounded-md bg-muted px-3 py-2">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="outline">{index + 1}</Badge>
              <span className="font-medium text-foreground">{step.title ?? step.stage}</span>
              {step.status ? <Badge variant="secondary">{step.status}</Badge> : null}
            </div>
            <StepEvidence evidence={step.evidence} />
            {step.related_fields && step.related_fields.length > 0 ? (
              <p className="mt-2 text-muted-foreground">
                相关字段：{step.related_fields.join(", ")}
              </p>
            ) : null}
            <StepOutputFields outputFields={outputFields} fieldLabels={fieldLabels} />
            <StepRouteValidation step={step} />
            <ProcessNotes notes={step.notes ?? []} />
            <TraceActionList actions={step.actions ?? []} />
            {"value" in step && outputFields.length === 0 ? (
              <dl className="mt-2 grid gap-2 sm:grid-cols-2">
                <div>
                  <dt className="text-muted-foreground">输出结果</dt>
                  <dd className="font-mono text-foreground">{stringifyValue(step.value)}</dd>
                </div>
              </dl>
            ) : null}
            {step.reason ? <p className="mt-2 text-muted-foreground">{step.reason}</p> : null}
            {step.failure_reason ? <p className="mt-2 text-destructive">{step.failure_reason}</p> : null}
          </div>
        );
      })}
    </div>
  );
}

function StepOutputFields({
  outputFields,
  fieldLabels
}: {
  outputFields: NonNullable<AgentProcessStep["output_fields"]>;
  fieldLabels: FieldLabelMap;
}) {
  if (outputFields.length === 0) {
    return null;
  }
  return (
    <div className="mt-2 space-y-2">
      <p className="text-muted-foreground">Agent 输出字段（route 前）</p>
      <div className="space-y-2">
        {outputFields.map((field, index) => (
          <div key={`${field.field_name}-${index}`} className="border-t pt-2">
            <dl className="grid gap-2 sm:grid-cols-3">
              <div>
                <dt className="text-muted-foreground">字段</dt>
                <dd className="mt-1 text-foreground">{getFieldLabel(fieldLabels, field.field_name)}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">值</dt>
                <dd className="mt-1 font-mono text-foreground">
                  {"value" in field ? stringifyValue(field.value) : "未输出值"}
                </dd>
              </div>
              {field.status ? (
                <div>
                  <dt className="text-muted-foreground">状态</dt>
                  <dd className="mt-1">
                    <Badge variant="outline">{field.status}</Badge>
                  </dd>
                </div>
              ) : null}
            </dl>
            {(field.reason || field.failure_reason) ? (
              <div className="mt-2">
                {field.reason ? <p className="text-muted-foreground">{field.reason}</p> : null}
                {field.failure_reason ? <p className="text-destructive">{field.failure_reason}</p> : null}
              </div>
            ) : null}
          </div>
        ))}
      </div>
    </div>
  );
}

function StepRouteValidation({ step }: { step: AgentProcessStep }) {
  if (step.stage !== "route_validation" && !step.route && typeof step.needs_review === "undefined") {
    return null;
  }
  return (
    <dl className="mt-2 grid gap-2 sm:grid-cols-2">
      {step.route ? (
        <div>
          <dt className="text-muted-foreground">Route 结论</dt>
          <dd className="mt-1">
            <Badge variant={getRouteStepBadgeVariant(step.route)}>
              {step.route}
            </Badge>
          </dd>
        </div>
      ) : null}
      {typeof step.needs_review !== "undefined" ? (
        <div>
          <dt className="text-muted-foreground">需要人工复核</dt>
          <dd className="mt-1 font-mono text-foreground">{step.needs_review ? "true" : "false"}</dd>
        </div>
      ) : null}
    </dl>
  );
}

function getRouteStepBadgeVariant(route: string): "success" | "warning" | "destructive" {
  if (route === "accept") {
    return "success";
  }
  if (route === "review") {
    return "warning";
  }
  return "destructive";
}

function StepEvidence({ evidence }: { evidence?: AgentProcessStep["evidence"] }) {
  if (!evidence) {
    return null;
  }
  const blockIds = evidence.block_ids ?? [];
  const candidateBlocks = buildCandidateBlocks(evidence);
  return (
    <div className="mt-2 space-y-1 text-muted-foreground">
      <CandidateBlockDetails blocks={candidateBlocks} />
      {candidateBlocks.length === 0 && blockIds.length > 0 ? (
        <p>候选 block 正文未返回</p>
      ) : null}
      <ProcessNotes notes={evidence.notes ?? []} />
      {candidateBlocks.length === 0 ? <EvidencePreview texts={evidence.texts ?? []} /> : null}
    </div>
  );
}

function CandidateBlockDetails({ blocks }: { blocks: EvidenceBlock[] }) {
  if (blocks.length === 0) {
    return null;
  }
  return (
    <details open className="rounded-md border bg-background px-3 py-2">
      <summary className="cursor-pointer text-xs font-medium text-foreground">
        候选 blocks（{blocks.length}）
      </summary>
      <div className="mt-2 space-y-2">
        {blocks.map((block, index) => (
          <div key={`${block.block_id ?? "block"}-${index}`} className="rounded-md bg-muted px-3 py-2">
            {block.text ? <MarkdownEvidence markdown={block.text} /> : null}
          </div>
        ))}
      </div>
    </details>
  );
}

function buildCandidateBlocks(evidence: NonNullable<AgentProcessStep["evidence"]>): EvidenceBlock[] {
  const explicitBlocks = (evidence.blocks ?? []).filter((block) => block.text);
  if (explicitBlocks.length > 0) {
    return explicitBlocks;
  }

  const refsWithText = (evidence.refs ?? [])
    .filter((ref) => ref.text)
    .map((ref) => ({
      document_id: ref.document_id,
      block_id: ref.block_id,
      page: ref.page,
      text: ref.text,
      kind: "text"
    }));
  if (refsWithText.length > 0) {
    return refsWithText;
  }

  const blockIds = evidence.block_ids ?? [];
  const refs = evidence.refs ?? [];
  return (evidence.texts ?? []).map((text, index) => ({
    document_id: refs[index]?.document_id,
    block_id: blockIds[index] ?? refs[index]?.block_id,
    page: refs[index]?.page,
    text,
    kind: "text"
  }));
}

function EvidencePreview({ texts }: { texts: string[] }) {
  if (texts.length === 0) {
    return null;
  }
  return (
    <ul className="space-y-1">
      {texts.slice(0, 2).map((text, index) => (
        <li key={`${text}-${index}`} className="line-clamp-2">
          候选文本：{compactMarkdown(text)}
        </li>
      ))}
    </ul>
  );
}

function compactMarkdown(value: string): string {
  return value
    .replace(/^#{1,6}\s*/gm, "")
    .replace(/\*\*/g, "")
    .replace(/\|/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function ProcessNotes({ notes }: { notes: string[] }) {
  if (notes.length === 0) {
    return null;
  }
  return (
    <ul className="mt-2 list-disc space-y-1 pl-4 text-muted-foreground">
      {notes.map((note, index) => (
        <li key={`${note}-${index}`}>{note}</li>
      ))}
    </ul>
  );
}

function TraceActionList({ actions }: { actions: TraceAction[] }) {
  if (actions.length === 0) {
    return null;
  }
  return (
    <div className="mt-3 space-y-2">
      <p className="text-muted-foreground">动作</p>
      {actions.map((action, index) => (
        <div key={`${action.action_type ?? "action"}-${index}`} className="rounded-md bg-muted px-3 py-2">
          <div className="flex flex-wrap items-center gap-2">
            {action.action_type ? <Badge variant="outline">{action.action_type}</Badge> : null}
            {action.used_in_final_decision ? <Badge variant="success">used</Badge> : null}
          </div>
          {action.message ? (
            <p className="mt-1 text-muted-foreground">{action.message}</p>
          ) : null}
          <ActionMetadata metadata={action.metadata} />
        </div>
      ))}
    </div>
  );
}

function ActionMetadata({ metadata }: { metadata?: Record<string, unknown> }) {
  if (!metadata) {
    return null;
  }
  const entries = flattenSummary(metadata);
  if (entries.length === 0) {
    return null;
  }
  return (
    <dl className="mt-2 grid gap-1 sm:grid-cols-2">
      {entries.map(([label, value]) => (
        <div key={label}>
          <dt className="text-muted-foreground">{label}</dt>
          <dd className="font-mono text-foreground">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function EvidenceList({ texts }: { texts: string[] }) {
  if (texts.length === 0) {
    return null;
  }
  return (
    <div className="mt-3 space-y-2">
      <p className="text-xs font-medium text-muted-foreground">证据文本</p>
      {texts.map((text, index) => (
        <blockquote key={`${text}-${index}`} className="border-l-2 border-primary pl-3">
          <MarkdownEvidence markdown={text} />
        </blockquote>
      ))}
    </div>
  );
}

function buildFieldLabels(detail: TaskDetailData): FieldLabelMap {
  const labels: FieldLabelMap = {};
  for (const field of detail.result?.fields ?? []) {
    if (field.display_name) {
      labels[field.field_name] = field.display_name;
    }
  }
  for (const field of detail.review?.fields ?? []) {
    if (field.display_name) {
      labels[field.field_name] = field.display_name;
    }
  }
  return labels;
}

function getFieldLabel(
  fieldLabels: FieldLabelMap,
  fieldName: string,
  displayName?: string | null,
): string {
  return displayName || fieldLabels[fieldName] || fieldName;
}

function StatusBadge({ status }: { status: TaskSummary["status"] }) {
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

function RouteBadge({ route }: { route: NonNullable<TaskSummary["route"]> }) {
  if (route === "accept") {
    return <Badge variant="success">route: {route}</Badge>;
  }
  if (route === "review") {
    return <Badge variant="warning">route: {route}</Badge>;
  }
  return <Badge variant="destructive">route: {route}</Badge>;
}
