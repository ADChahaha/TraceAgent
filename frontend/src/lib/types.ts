export type TaskStatus =
  | "pending"
  | "processing"
  | "completed"
  | "failed";

export type TaskStage =
  | "uploaded"
  | "document_processing"
  | "extraction"
  | "done";

export type BasicFieldType = "string" | "number" | "boolean" | "list[string]" | "list[number]" | "null";
export type TaskFieldType = BasicFieldType | "enum";

export interface EnumVariantDefinition {
  name: string;
  type: BasicFieldType | string;
  description?: string | null;
}

export interface Capabilities {
  supported_file_types: string[];
  task_types: string[];
  features: {
    trace: boolean;
    audit: boolean;
    external_task_spec: boolean;
    multiple_files?: boolean;
  };
}

export interface TaskCreated {
  task_id: string;
  status: TaskStatus;
  stage: TaskStage;
  error_message?: string | null;
  stream?: TaskStreamState;
}

export interface TaskSummary {
  task_id: string;
  status: TaskStatus;
  stage: TaskStage;
  error_message?: string | null;
  has_result?: boolean;
  has_trace?: boolean;
  created_at?: string;
  updated_at?: string;
  stream?: TaskStreamState;
}

export interface TaskStreamState {
  state: "running" | "ended" | string;
  last_event_seq: number;
}

export interface TaskList {
  tasks: TaskSummary[];
}

export interface TaskResultField {
  field_name: string;
  display_name?: string | null;
  field_type?: TaskFieldType | string | null;
  variants?: EnumVariantDefinition[];
  agent_value: unknown;
  final_value: unknown;
  field_status?: string;
  source?: "agent" | string | null;
  committed?: boolean;
}

export interface TaskResult {
  task_id: string;
  status: TaskStatus;
  fields: TaskResultField[];
}

export interface EvidenceRef {
  document_id?: string;
  page?: number;
  span?: string | null;
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
  tool_name?: string;
  message?: string;
  args?: Record<string, unknown>;
  result?: unknown;
  refs?: EvidenceRef[];
  evidence_ids?: string[];
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

export interface AuditCommit {
  field_name: string;
  final_value: unknown;
  agent_value?: unknown;
  evidence_refs?: EvidenceRef[];
  used_global_lookup?: boolean;
  used_validation_rule?: boolean;
  action_types?: string[];
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
  replay: TaskReplay | null;
  audit: AuditResult | null;
}

export interface TaskReplay {
  task_id: string;
  status: TaskStatus;
  stage: TaskStage | string;
  documents: Array<{
    document_id: string;
    filename: string;
  }>;
  display_html: string;
  outline_tree?: ReplayOutlineNode[];
  source_selectors?: Record<string, string>;
  broad_plan?: ReplayBroadPlan | null;
  actions: ReplayAction[];
  result?: {
    fields?: TaskResultField[];
    [key: string]: unknown;
  } | Record<string, unknown>;
  field_states?: Record<string, ReplayFieldState>;
  audit?: Record<string, unknown>;
}

export interface ReplayBroadPlan {
  summary?: string;
  plan?: string[];
  risks?: string[];
}

export interface ReplayOutlineNode {
  id?: string;
  type?: string;
  text?: string;
  label?: string | null;
  children?: ReplayOutlineNode[];
}

export interface ReplayAction {
  tool_name?: string;
  action_type?: string;
  reason?: string | null;
  args?: Record<string, unknown>;
  result?: unknown;
  message?: string;
  metadata?: Record<string, unknown>;
  refs?: EvidenceRef[];
}

export interface ReplayFieldState {
  name?: string;
  field_name?: string;
  status?: string;
  value?: unknown;
  evidence_ids?: string[];
  failure_reason?: string | null;
}
