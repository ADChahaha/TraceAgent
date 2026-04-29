export type TaskStatus =
  | "pending"
  | "processing"
  | "waiting_review"
  | "completed"
  | "rejected"
  | "failed";

export type TaskStage =
  | "uploaded"
  | "document_processing"
  | "extraction"
  | "route_policy"
  | "review"
  | "field_commit"
  | "done";

export type RouteDecision = "accept" | "review" | "reject";
export type ReviewDecision = "approve" | "revise_and_approve" | "reject";

export interface Capabilities {
  supported_file_types: string[];
  task_types: string[];
  routes: RouteDecision[];
  review_decisions: ReviewDecision[];
  features: {
    trace: boolean;
    review: boolean;
    audit: boolean;
    external_task_spec: boolean;
    multiple_files?: boolean;
  };
}

export interface TaskCreated {
  task_id: string;
  status: TaskStatus;
  stage: TaskStage;
}

export interface TaskSummary extends TaskCreated {
  route?: RouteDecision | null;
  route_reason?: string | null;
  has_result?: boolean;
  has_trace?: boolean;
  needs_review?: boolean;
  created_at?: string;
  updated_at?: string;
}

export interface TaskResultField {
  field_name: string;
  display_name?: string | null;
  agent_value: unknown;
  review_value: unknown;
  final_value: unknown;
  field_status?: string;
  route?: RouteDecision | null;
  source?: "agent" | "human" | string | null;
  committed?: boolean;
}

export interface TaskResult {
  task_id: string;
  status: TaskStatus;
  route?: RouteDecision | null;
  fields: TaskResultField[];
}

export interface EvidenceRef {
  document_id?: string;
  page?: number;
  block_id?: string;
  text?: string;
}

export interface EvidenceBlock {
  document_id?: string;
  block_id?: string;
  page?: number;
  text?: string;
  kind?: string;
}

export interface EvidencePayload {
  block_ids?: string[];
  blocks?: EvidenceBlock[];
  texts?: string[];
  refs?: EvidenceRef[];
  status?: string;
  notes?: string[];
}

export interface TraceAction {
  action_type?: string;
  message?: string;
  used_in_final_decision?: boolean;
  metadata?: Record<string, unknown>;
}

export interface TraceField {
  field_name: string;
  status?: string;
  evidence?: EvidencePayload;
  related_fields?: string[];
  actions?: TraceAction[];
  process_steps?: AgentProcessStep[];
  reason?: string | null;
  failure_reason?: string | null;
}

export interface AgentProcessStep {
  stage: string;
  title?: string;
  status?: string | null;
  evidence?: EvidencePayload;
  related_fields?: string[];
  actions?: TraceAction[];
  output_fields?: AgentProcessOutputField[];
  route?: string | null;
  needs_review?: boolean;
  notes?: string[];
  value?: unknown;
  reason?: string | null;
  failure_reason?: string | null;
}

export interface AgentProcessOutputField {
  field_name: string;
  status?: string | null;
  value?: unknown;
  reason?: string | null;
  failure_reason?: string | null;
}

export interface AgentProcess {
  field_name: string;
  status?: string;
  value?: unknown;
  evidence?: EvidencePayload;
  related_fields?: string[];
  actions?: TraceAction[];
  process_steps?: AgentProcessStep[];
  reason?: string | null;
  failure_reason?: string | null;
}

export interface TraceStep {
  stage: TaskStage | string;
  agent: string;
  status: string;
  started_at?: string | null;
  finished_at?: string | null;
  failure_reason?: string | null;
  summary?: Record<string, unknown>;
  documents?: Array<{
    document_id?: string;
    filename: string;
    file_type?: string;
    content_type?: string | null;
    block_count?: number;
    markdown_chars?: number;
    warning_count?: number;
    processed_at?: string | null;
  }>;
  routes?: Array<{
    field_name: string;
    route: RouteDecision | string;
    needs_review?: boolean;
    route_reason?: string | null;
  }>;
  field_decisions?: AgentProcess[];
  warnings?: string[];
  metadata?: Record<string, unknown>;
  is_terminal_step?: boolean;
}

export interface AgentTraceRecord {
  id?: string;
  sequence: number;
  stage: TaskStage | string;
  agent: string;
  status: string;
  failure_reason?: string | null;
  request?: Record<string, unknown>;
  response?: Record<string, unknown>;
  trace?: Record<string, unknown>;
  started_at?: string | null;
  finished_at?: string | null;
}

export interface TaskTrace {
  task_id: string;
  agent_status?: string;
  failure_reason?: string | null;
  steps?: TraceStep[];
  agent_trace?: AgentTraceRecord[];
  fields: TraceField[];
  metadata?: Record<string, unknown>;
}

export interface ReviewField {
  field_name: string;
  display_name?: string | null;
  agent_value: unknown;
  field_status?: string;
  needs_review: boolean;
  review_reason?: string | null;
  evidence_texts?: string[];
  evidence_refs?: EvidenceRef[];
  related_fields?: string[];
  actions?: string[];
  reason?: string | null;
  failure_reason?: string | null;
  agent_process?: AgentProcess | null;
}

export interface ReviewHandoff {
  task_id: string;
  status: TaskStatus;
  route?: RouteDecision | null;
  route_reason?: string | null;
  fields: ReviewField[];
}

export interface AuditCommit {
  field_name: string;
  final_value: unknown;
  route?: RouteDecision | null;
  reviewed?: boolean;
  review_decision?: ReviewDecision | null;
  agent_value?: unknown;
  review_value?: unknown;
  evidence_refs?: EvidenceRef[];
  used_global_lookup?: boolean;
  used_validation_rule?: boolean;
  related_fields?: string[];
  committed_by?: string;
  committed_at?: string;
  agent_process?: AgentProcess | null;
}

export interface AuditResult {
  task_id: string;
  status: TaskStatus;
  field_commits: AuditCommit[];
}

export interface TaskDetailData {
  summary: TaskSummary;
  result: TaskResult | null;
  trace: TaskTrace | null;
  review: ReviewHandoff | null;
  audit: AuditResult | null;
}

export interface ReviewSubmitPayload {
  decision: ReviewDecision;
  fields: Array<{
    field_name: string;
    review_value?: unknown;
    comment?: string | null;
  }>;
  comment?: string | null;
  reviewer?: string | null;
}
