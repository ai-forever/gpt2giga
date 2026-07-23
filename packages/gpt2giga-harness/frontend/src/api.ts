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

export interface EnvironmentResponse {
  environment: {
    schema_version: number;
    provider_id: string;
    repository_root: string;
    worktree_root: string;
    branch: string | null;
    detached: boolean;
    head: string | null;
    base_identity: string | null;
    upstream: string | null;
    ahead: number;
    behind: number;
    remote: string | null;
    staged_count: number;
    unstaged_count: number;
    untracked_count: number;
    additions: number;
    deletions: number;
    changed_paths: string[];
    changed_paths_truncated: boolean;
    diff_sha256: string;
    captured_at: string;
    push_ready: boolean;
    push_blocker: string | null;
  };
  commit: { blocker: string | null; ready: boolean };
  github: {
    schema_version: number;
    status: string;
    auth_status: string;
    checked_at: string;
    repository: {
      host: string;
      name_with_owner: string;
      url: string;
      default_branch: string | null;
      is_fork: boolean;
    } | null;
    pull_request: {
      number: number;
      state: string;
      url: string;
      draft: boolean;
      head_branch: string;
      base_branch: string;
      checks: GitHubCountRollup;
      issues: { number: number; state: string; url: string }[];
    } | null;
    runs: {
      database_id: number;
      status: string;
      conclusion: string | null;
      url: string;
      head_sha: string;
      created_at: string;
      updated_at: string;
      jobs: GitHubCountRollup;
    }[];
    reason_code: string | null;
    cached: boolean;
    stale: boolean;
  };
  issue_pr: {
    status: string;
    kind?: string;
    number?: number;
    url?: string;
    checks?: GitHubCountRollup;
    issues?: { number: number; state: string; url: string }[];
  };
  freshness: { captured_at: string; status: string };
}

export interface EnvironmentCommitPreview {
  id: string;
  branch: string;
  head: string | null;
  diff_sha256: string;
  staged_count: number;
  message: string;
  author: { name: string; email: string };
  worktree_root: string;
}

export interface EnvironmentCommitPreviewResponse {
  preview: EnvironmentCommitPreview;
}

export interface EnvironmentCommitApplyResponse {
  approval_required?: boolean;
  approval?: ApprovalRequest;
  preview: EnvironmentCommitPreview;
  result?: {
    preview_id: string;
    commit_head: string;
    parent_head: string | null;
    completed_at: string;
    recovered: boolean;
  };
  idempotent_replay?: boolean;
}

export interface EnvironmentPushPreview {
  id: string;
  repository: { host: string; name_with_owner: string };
  branch: string;
  head: string;
  diff_sha256: string;
  remote: string;
  upstream: string | null;
  target_branch: string;
  remote_ref: string;
  remote_head: string | null;
  permissions: {
    network_connect: boolean;
    remote_write: boolean;
    create_remote_branch: boolean;
    set_upstream: boolean;
    force_update: boolean;
    delete_remote_branch: boolean;
    follow_tags: boolean;
    execute_hooks: boolean;
  };
  worktree_root: string;
}

export interface EnvironmentPushPreviewResponse {
  preview: EnvironmentPushPreview;
}

export interface EnvironmentPushApplyResponse {
  approval_required?: boolean;
  approval?: ApprovalRequest;
  preview: EnvironmentPushPreview;
  result?: {
    preview_id: string;
    commit_head: string;
    remote: string;
    target_branch: string;
    remote_commit_url: string;
    run_evidence_url: string;
    upstream_configured: boolean;
    completed_at: string;
    recovered: boolean;
  };
  idempotent_replay?: boolean;
}

export interface EnvironmentPullRequestPreview {
  id: string;
  repository: { host: string; name_with_owner: string; url: string };
  remote: string;
  source_branch: string;
  source_head: string;
  source_remote_head: string;
  base_branch: string;
  base_head: string;
  diff_sha256: string;
  title: string;
  body: string;
  worktree_root: string;
}

export interface EnvironmentPullRequestPreviewResponse {
  preview: EnvironmentPullRequestPreview;
}

export interface EnvironmentPullRequestApplyResponse {
  approval_required?: boolean;
  approval?: ApprovalRequest;
  preview: EnvironmentPullRequestPreview;
  result?: {
    preview_id: string;
    number: number;
    state: string;
    source_branch: string;
    base_branch: string;
    commit_head: string;
    pull_request_url: string;
    commit_url: string;
    checks_url: string;
    run_evidence_url: string;
    completed_at: string;
    recovered: boolean;
  };
  idempotent_replay?: boolean;
}

export interface GitHubCountRollup {
  status: string;
  total: number;
  passed: number;
  failed: number;
  pending: number;
  skipped: number;
  cancelled: number;
  unknown: number;
}

export interface MessageProjection {
  id: string;
  run_id?: string | null;
  edited_from_message_id?: string;
  role: string;
  created_at: string;
  content: TextProjection;
  reasoning?: TextProjection;
  usage?: TokenUsageProjection;
}

export interface FullMessageResponse {
  message_id: string;
  role: string;
  content: string;
  byte_count: number;
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
  execution_transport?: string | null;
  provider_session?: {
    link_id?: string | null;
    external_session_id?: string | null;
    latest_external_turn_id?: string | null;
    recovery_state?: string | null;
    protocol?: string | null;
    protocol_version?: string | null;
    link_hash?: string | null;
    content_free: true;
  } | null;
  native_process_id?: string | null;
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

export type TraceReplayAxis = "model" | "provider" | "harness" | "extensions";

export interface TraceReplayManifest {
  schema_version: number;
  source_run_id: string;
  source_session_id: string;
  task_sha256: string;
  source_evidence_sha256: string;
  axis: TraceReplayAxis;
  source_dimensions: Record<TraceReplayAxis, unknown>;
  target_dimensions: Record<TraceReplayAxis, unknown>;
  fixed_dimensions: Record<string, unknown>;
  unchanged_snapshot_sha256: string;
  created_at: string;
  manifest_sha256: string;
  content_free: true;
}

export interface TraceReplayPreviewResponse {
  manifest: TraceReplayManifest;
  admission: { admitted: boolean; reason_code: string | null };
  execution: {
    new_session: boolean;
    workspace_policy: string;
    provider_session: string;
    external_telemetry_required: boolean;
    automatic_apply: boolean;
  };
}

export interface TraceReplayProjection {
  schema_version: number;
  manifest: TraceReplayManifest;
  source: TraceReplayRunRef;
  destination: TraceReplayRunRef;
  source_evidence_current: boolean;
  snapshot_equality: {
    status: "pending" | "verified" | "mismatch";
    changed_axes: TraceReplayAxis[];
    unchanged_verified: boolean;
    target_verified: boolean;
  };
  comparison_status: "pending" | "ready";
  comparison: {
    semantic: TraceReplayPair;
    tools: TraceReplayPair;
    diff: TraceReplayPair;
    latency: TraceReplayNumericPair;
    cost: TraceReplayCostPair;
  };
  external_telemetry_required: boolean;
  automatic_apply: boolean;
}

interface TraceReplayRunRef {
  run_id: string;
  session_id: string;
  status: string;
  harness_id: string;
  model: string | null;
  workspace_isolated: boolean;
}

interface TraceReplayPair {
  source: Record<string, unknown>;
  target: Record<string, unknown> | null;
  changed: boolean | null;
}

interface TraceReplayNumericPair {
  source: number | null;
  target: number | null;
  delta: number | null;
  unit: string;
}

interface TraceReplayCostPair {
  source: { value: number | null; unit: string | null; confidence: string };
  target: { value: number | null; unit: string | null; confidence: string } | null;
  delta: number | null;
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
  compatibility?: {
    compatible?: boolean;
    status?: string;
    version?: string | null;
    warning?: string | null;
  } | null;
  execution_surfaces?: Array<{
    id: string;
    status: string;
    ownership: string;
    queueable: boolean;
    detail: string;
    blocker?: string | null;
  }>;
  provider_handoff?: {
    status: string;
    provider_ui_handoff: boolean;
    available_actions: string[];
    degraded_actions: string[];
    blocker?: string | null;
    queueable: false;
    durable: false;
    content_free: true;
  } | null;
  workbench_transport?: {
    default: "native_structured" | "native_terminal" | "one_shot";
    options: Array<{
      id: "native_structured" | "native_terminal" | "one_shot";
      status: string;
      detail: string;
      blocker?: string | null;
      remediation?: string | null;
      durable: boolean;
      provider_native_continuity: boolean;
    }>;
  };
}

export interface HarnessesResponse {
  harnesses: HarnessOption[];
  discovery_errors?: string[];
}

export interface HandoffCapsuleResponse {
  capsule: {
    capsule_id: string;
    capsule_sha256: string;
    content_free: true;
    summary: {
      artifact_count: number;
      pending_approval_count: number;
      unresolved_question_count: number;
    };
    provenance: {
      source: { harness_id: string };
      target: { harness_id: string; session_requirement: string };
    };
    environment: {
      branch: string | null;
      head: string | null;
      snapshot_sha256: string;
    };
    continuity: {
      native_session_identity_preserved: false;
      provider_session_identity_preserved: false;
      claim: "evidence_handoff_only";
    };
  };
}

export interface ModelsResponse {
  ok: boolean;
  models: string[];
  source?: string;
  error?: string | null;
  note?: string | null;
}

export interface SettingsResponse {
  revision: string;
  runtime: {
    proxy_url: string;
    proxy_source: string;
    proxy_health: string;
    auto_start_proxy: boolean;
    change_effect: string;
    editable: false;
    proxy_auth_configured: boolean;
  };
  provider: {
    configured: boolean;
    count: number;
    source: string;
    health: string;
    secret_readable: false;
    change_effect: string;
    registry_path_readable: false;
  };
  routes: {
    default_api_mode: string;
    default_model: string | null;
    models: string[];
    models_source: string;
    health: string;
    change_effect: string;
  };
  harness_defaults: {
    default_harness_id: string;
    default_model: string | null;
    default_title_model: string | null;
    default_api_mode: string;
    mode: string;
    execution_transport: string;
    invocation_mode: string;
    workspace_policy: string;
    permission_profile: string;
    stream: boolean;
    harnesses: Array<{
      id: string;
      title: string;
      native_supported: boolean;
      status: string;
      workbench_transport: NonNullable<HarnessOption["workbench_transport"]>;
    }>;
    sources: Record<string, string>;
    locked_fields: string[];
    change_effect: "new_runs";
  };
  workspace: {
    project_id: string;
    name: string;
    is_git_repo: boolean;
    trusted: boolean | null;
    workspace_policies: string[];
    permission_profiles: string[];
    source: string;
  };
  mcp: {
    servers: Array<{
      id: string;
      title: string;
      transport: string;
      enabled: boolean;
      trusted: boolean;
      source: string;
      health: string;
    }>;
    errors: Array<{ server_id?: string; error?: string }>;
    change_effect: string;
  };
  diagnostics: {
    content_free: true;
    actions: Array<{ id: string; method: string; path: string }>;
    async_data_plane: Record<string, unknown>;
  };
}

export interface SettingsSaveResponse {
  saved: true;
  revision: string;
  defaults: Omit<SettingsResponse["harness_defaults"], "harnesses" | "sources" | "locked_fields" | "change_effect">;
  sources: Record<string, string>;
  locked_fields: string[];
  change_effect: "new_runs";
}

export interface ProviderHealthProjection {
  status: string;
  checked_at: string;
  duration_ms: number;
  discovery_status: string;
  failure_kind: string | null;
  reason_code: string | null;
  discovery_reason_code: string | null;
  cached: boolean;
  models: Array<{ model: string; source: string }>;
}

export interface ProviderProjection {
  id: string;
  display_name: string;
  protocol: string;
  dialect: string;
  base_url: string;
  route_prefix: string | null;
  effective_base_url: string;
  source: string;
  enabled: boolean;
  offline: boolean;
  registry_revision: number;
  profile_revision: string;
  authentication: {
    ownership: string;
    reference_kind: string | null;
    reference_name: string | null;
    service: string | null;
    account: string | null;
    value_readable: false;
    explanation: string;
  };
  default_models: Partial<Record<"coding" | "title" | "evaluation" | "fallback", string>>;
  routes: Array<{
    id: string;
    revision: string;
    purpose: string;
    model: string;
    provider_revision: string;
    authentication_ownership: string;
  }>;
  compatibility: Array<{
    harness_id: string;
    adapter_version: string;
    transports: string[];
    native_auth: boolean;
    capabilities: string[];
    evidence_status: "reviewed";
  }>;
  compatibility_explanation: string;
  health: ProviderHealthProjection | null;
  effects: Record<string, string>;
  updated_at: string;
}

export interface ProviderSettingsResponse {
  providers: ProviderProjection[];
  templates: Array<{
    id: string;
    title: string;
    protocol: string;
    dialect: string;
    base_url: string;
    route_prefix: string | null;
    authentication: string;
    secret_reference_name: string | null;
  }>;
  effects: Record<string, string>;
  secret_contract: {
    accepted_reference_kinds: string[];
    values_accepted: false;
    values_returned: false;
    filesystem_paths_accepted: false;
  };
  discovery_errors: string[];
}

export interface ProviderMutationResponse {
  saved: true;
  provider: ProviderProjection;
  effects: Record<string, string>;
}

export interface ProviderCheckResponse {
  provider_id: string;
  health: ProviderHealthProjection;
  effects: Record<string, string>;
}

export interface AttachmentSummary {
  id: string;
  filename: string;
  workspace_path?: string | null;
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

export interface WorkspaceFileCandidate {
  path: string;
  name: string;
  kind: string;
  mime_type?: string | null;
  size_bytes: number;
}

export interface WorkspaceFileSearchResponse {
  q: string;
  files: WorkspaceFileCandidate[];
  bounded: true;
}

export interface ArenaWorkspaceFileSearchResponse {
  workspace: string;
  q: string;
  files: WorkspaceFileCandidate[];
}

export interface ArenaMessageProjection {
  id: string;
  run_id?: string | null;
  role: string;
  content: string;
  created_at: string;
  metadata?: { usage?: TokenUsageProjection; attachments?: unknown[] };
}

export interface ArenaActivityProjection {
  id: string;
  run_id: string;
  type: string;
  message?: string;
  payload?: Readonly<Record<string, unknown>>;
  created_at?: string;
}

export interface ArenaChildProjection {
  harness_id: string;
  index: number;
  session_id: string | null;
  run_id: string | null;
  status: string;
  error?: string | null;
  result_text?: string | null;
  run?: RunSummary;
  runs?: RunSummary[];
  messages?: ArenaMessageProjection[];
  activity?: ArenaActivityProjection[];
  bounded?: true;
}

export interface ArenaCandidateEvidence {
  child_index: number;
  harness_id: string;
  session_id: string | null;
  run_id: string | null;
  status: string;
  configuration_sha256: string | null;
  artifact_sha256: string | null;
  metrics: Readonly<Record<string, number>>;
  cost: {
    confidence: "exact" | "estimated" | "unknown";
    value: number | null;
    unit: string | null;
  };
}

export interface ArenaVerdict {
  candidate_set_sha256: string;
  selected_child_index: number;
  selected_run_id: string;
  scores: { child_index: number; score: number }[];
  decided_at: string;
  verdict_sha256: string;
  current: boolean;
  promotion: {
    selected_run_id: string;
    configuration_preview_url: string;
    artifact_review_url: string;
    run_url: string;
    automatic_apply: false;
  };
}

export interface ArenaProjectionResponse {
  arena: {
    id: string;
    session_id: string;
    status: string;
    prompt: string;
    harness_ids: string[];
    model: string | null;
    api_mode: string;
    mode: string;
    workspace: string | null;
    attachment_ids: string[];
    created_at: string;
    updated_at: string;
    child_runs: ArenaChildProjection[];
    review: {
      schema_version: number;
      task_sha256: string;
      candidate_set_sha256: string;
      candidates: ArenaCandidateEvidence[];
      verdict: ArenaVerdict | null;
    };
    metadata: {
      turn_count?: number;
    };
  };
}

export interface NativeProcessProjection {
  id: string;
  status: string;
  run_id?: string | null;
  session_id?: string | null;
}

export interface NativeStartResponse {
  process: NativeProcessProjection;
  run: RunSummary;
}

export interface NativeOutputResponse {
  cursor: number;
  status?: string;
  terminal?: boolean;
  process?: NativeProcessProjection;
  run?: RunSummary | null;
}

export interface RunPreflightResponse {
  preflight: {
    ok: boolean;
    hard_block: boolean;
    max_severity: string;
    findings: Array<{ id: string; severity: string; message: string }>;
    readiness?: { status?: string; findings?: unknown[] };
    permission_simulation?: {
      simulation_hash: string;
      block_run: boolean;
      blocked_actions: string[];
      approval_points: string[];
      summary: {
        allowed: number;
        approval_required: number;
        denied: number;
        unknown: number;
      };
      route_snapshot: {
        snapshot_hash: string;
        harness_id: string;
        execution_transport: string;
        extension_count: number;
      };
      outcomes: Array<{
        domain: string;
        action: string | null;
        prediction: string;
        occurrence: string;
        control_owner: string;
        reason_code: string;
      }>;
      content_free: boolean;
      side_effect_free: boolean;
      provider_safety_proven: boolean;
    };
  };
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

export async function putCockpit<T>(
  path: string,
  body: Readonly<Record<string, unknown>>,
  signal?: AbortSignal,
): Promise<T> {
  return writeCockpit<T>(path, "PUT", body, signal);
}

export async function deleteCockpit<T>(
  path: string,
  signal?: AbortSignal,
): Promise<T> {
  return writeCockpit<T>(path, "DELETE", undefined, signal);
}

async function writeCockpit<T>(
  path: string,
  method: "DELETE" | "PATCH" | "POST" | "PUT",
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
    const body = await response.text();
    let detail = body;
    try {
      const parsed = JSON.parse(body) as unknown;
      if (
        typeof parsed === "object" &&
        parsed !== null &&
        "detail" in parsed &&
        typeof parsed.detail === "string"
      ) {
        detail = parsed.detail;
      }
    } catch {
      // Preserve non-JSON server errors as returned.
    }
    throw new CockpitApiError(
      response.status,
      detail || `Request failed with HTTP ${response.status}.`,
    );
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
