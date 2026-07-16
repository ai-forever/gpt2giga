export interface TextProjection {
  text: string;
  byte_count: number;
  truncated: boolean;
}

export interface SessionSummary {
  id: string;
  title: string;
  created_at?: string;
  updated_at: string;
  default_harness_id?: string;
  default_model?: string | null;
  default_api_mode?: string;
  default_mode?: string;
  project_id?: string | null;
  workspace_bound?: boolean;
  pinned: boolean;
  archived: boolean;
  tags?: string[];
}

export interface MessageProjection {
  id: string;
  run_id?: string | null;
  role: string;
  created_at: string;
  content: TextProjection;
  reasoning?: TextProjection;
  usage?: TokenUsageProjection;
}

export interface TokenUsageProjection {
  input_tokens?: number;
  output_tokens?: number;
  total_tokens?: number;
  cached_input_tokens?: number;
  reasoning_output_tokens?: number;
  tool_tokens?: number;
}

export interface RunSummary {
  id: string;
  session_id: string;
  harness_id?: string;
  status: string;
  model?: string | null;
  api_mode?: string;
  capability?: string;
  mode?: string;
  invocation_mode?: string;
  created_at?: string;
  updated_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  artifacts?: ArtifactProjection[];
}

export interface ArtifactProjection {
  type: string;
  byte_count?: number | null;
  projection_url?: string;
  source?: string;
  step_id?: string;
}

export interface CursorPage<T> {
  has_more: boolean;
  next_cursor: string | null;
  snapshot_revision: string;
  byte_count: number;
  items: T[];
}

export interface SessionIndexResponse {
  sessions: SessionSummary[];
  has_more: boolean;
  next_cursor: string | null;
  snapshot_revision: string;
  byte_count: number;
}

export interface SessionOverviewResponse {
  session: SessionSummary;
  snapshot_revision: string;
  projections: Record<string, string>;
}

export interface SessionMessagesResponse {
  messages: MessageProjection[];
  has_more: boolean;
  next_cursor: string | null;
  snapshot_revision: string;
  byte_count: number;
}

export interface SessionRunsResponse {
  runs: RunSummary[];
  has_more: boolean;
  next_cursor: string | null;
  snapshot_revision: string;
  byte_count: number;
}

export interface RunOverviewResponse {
  run: RunSummary;
  snapshot_revision: string;
  projections: Record<string, string>;
}

export interface RunOwnership {
  job_id: string;
  job_status: string;
  attempt_id: string | null;
  attempt_number: number | null;
  attempt_status: string | null;
  worker_id: string | null;
  heartbeat_at: string | null;
  leased_until: string | null;
}

export interface ApprovalRequest {
  id: string;
  action: string;
  status: string;
  enforcement: string;
  policy_source: string;
  enforcement_owner: string;
  reason?: string;
  preview?: Record<string, unknown>;
  project_id?: string | null;
  session_id?: string | null;
  run_id?: string | null;
  job_id?: string | null;
  decision: string | null;
  expires_at: string | null;
  decided_at: string | null;
  created_at: string;
}

export interface RunExplanation {
  key: string;
  title: string;
  status: string;
  summary: string;
  details: string[];
}

export interface RunsCenterItem {
  run_id: string;
  session_id: string;
  session_title: string;
  status_group: string;
  attempt_count: number;
  retry_count: number;
  worker_id: string | null;
  duration_ms: number | null;
  run: RunSummary | null;
  ownership: RunOwnership;
  approvals: ApprovalRequest[];
  explanations: RunExplanation[];
  artifact_inventory: ArtifactProjection[];
  actions: Record<string, string | null>;
}

export interface RunsCenterResponse {
  runs: RunsCenterItem[];
  next_cursor: string | null;
  workers: Array<{ id: string; status: string; heartbeat_at: string }>;
}

export interface RunCenterSummaryResponse {
  run: RunsCenterItem;
}

export interface TraceNode {
  id: string;
  event_id?: string;
  run_id: string;
  kind: string;
  status?: string | null;
  title: string;
  event_type?: string;
  created_at: string;
  duration_ms?: number | null;
  worker_id?: string | null;
  has_payload: boolean;
}

export interface RunTraceResponse {
  run_id: string;
  nodes: TraceNode[];
  next_cursor: string | null;
  live: boolean;
}

export interface ApprovalInboxResponse {
  approvals: ApprovalRequest[];
  pending_count: number;
}

export interface AttentionItem {
  id: string;
  kind: string;
  severity: string;
  title: string;
  summary: string;
  href: string;
  created_at: string;
  read: boolean;
}

export interface AttentionInboxResponse {
  items: AttentionItem[];
  unread: number;
  counts: Record<string, number>;
}

export interface RunStartResponse {
  session: SessionSummary;
  run: RunSummary;
  stream_url: string;
  cancel_url: string;
  job?: { status?: string };
}

export interface HarnessOption {
  spec: {
    capabilities?: string[];
    id: string;
    title?: string;
    supported_builtin_tools?: string[];
    supports_api_mode_selection?: boolean;
    supports_attachments?: boolean;
    supports_model_selection?: boolean;
    supports_native_sessions?: boolean;
  };
  availability?: { status?: string; reason?: string | null };
}

export interface HarnessesResponse {
  harnesses: HarnessOption[];
  discovery_errors?: string[];
}

export interface ModelsResponse {
  ok: boolean;
  models: string[];
  source?: string;
  error?: string | null;
  note?: string | null;
}

export interface AttachmentSummary {
  id: string;
  filename: string;
  kind?: string;
  mime_type?: string | null;
  size_bytes: number;
  warnings?: string[];
}

export interface AttachmentsResponse {
  attachments: AttachmentSummary[];
}

export interface AttachmentUploadResponse {
  attachment: AttachmentSummary;
}

export interface EventProjection {
  id: string;
  run_id: string;
  type: string;
  message?: TextProjection;
  payload_url: string;
  created_at?: string;
}

export interface SessionEventsResponse {
  events: EventProjection[];
  has_more: boolean;
  next_cursor: string | null;
  snapshot_revision: string;
  byte_count: number;
}

export interface EventPayloadResponse {
  event_id: string;
  hidden: boolean;
  payload: Readonly<Record<string, unknown>>;
}

export class CockpitApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "CockpitApiError";
    this.status = status;
  }
}

export async function fetchCockpit<T>(
  path: string,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(path, {
    headers: { Accept: "application/json" },
    signal,
  });
  return parseResponse<T>(response);
}

export async function mutateCockpit<T>(
  path: string,
  body?: Readonly<Record<string, unknown>>,
  signal?: AbortSignal,
): Promise<T> {
  return writeCockpit<T>(path, "POST", body, signal);
}

export async function patchCockpit<T>(
  path: string,
  body: Readonly<Record<string, unknown>>,
  signal?: AbortSignal,
): Promise<T> {
  return writeCockpit<T>(path, "PATCH", body, signal);
}

export async function deleteCockpit<T>(
  path: string,
  signal?: AbortSignal,
): Promise<T> {
  return writeCockpit<T>(path, "DELETE", undefined, signal);
}

async function writeCockpit<T>(
  path: string,
  method: "DELETE" | "PATCH" | "POST",
  body?: Readonly<Record<string, unknown>>,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(path, {
    body: body === undefined ? undefined : JSON.stringify(body),
    headers: {
      Accept: "application/json",
      ...(body === undefined ? {} : { "Content-Type": "application/json" }),
    },
    method,
    signal,
  });
  return parseResponse<T>(response);
}

async function parseResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    throw new CockpitApiError(response.status, await response.text());
  }
  return (await response.json()) as T;
}

export function withQuery(
  path: string,
  values: Readonly<Record<string, string | number | boolean | null | undefined>>,
): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (value !== null && value !== undefined && value !== "") {
      search.set(key, String(value));
    }
  }
  const query = search.toString();
  return query ? `${path}?${query}` : path;
}
