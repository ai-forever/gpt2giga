import { queryOptions } from "@tanstack/react-query";

import {
  type ArenaProjectionResponse,
  type ArenaWorkspaceFileSearchResponse,
  fetchCockpit,
  withQuery,
} from "./api";
import {
  projectAutomation,
  projectEvaluation,
  projectMcpServers,
} from "./surface-projections";

const rootKey = ["cockpit", "remaining-surfaces"] as const;

export interface IntegrationFlowInventory {
  sources: Array<{ id: string; network_required: boolean }>;
  targets: Array<{
    id: string;
    component_types: string[];
    scopes: string[];
    execution_owner: string;
  }>;
  catalog: Array<{
    catalog_id: string;
    package_id: string;
    version: string;
    component_types: string[];
    target_ids: string[];
    scopes: string[];
    trust_decision: string;
    source_type: string;
    discovery?: {
      name: string;
      component: string;
      detail_url: string | null;
      artifact_url: string | null;
      popularity: number | null;
      curated: boolean;
    } | null;
  }>;
  root_skills?: Array<{
    id: string;
    name: string;
    description: string;
    target_ids: string[];
    origin: string;
    scope: "root";
    connected: true;
    preview_id: string;
  }>;
  flows: IntegrationFlowSummary[];
  groups: IntegrationGroupSummary[];
  content_free: true;
}

export interface IntegrationSearchResponse {
  query: string;
  items: Array<{
    id: string;
    source_id: string;
    upstream_id: string;
    title: string;
    component: "skill" | "mcp";
    artifact_url: string | null;
    detail_url: string | null;
    curated: boolean;
    popularity: number | null;
    upstream_audit: string | null;
    install_authorized: false;
  }>;
  sources: Array<{ id: string; status: string; error_type: string | null }>;
  install_authorized: false;
}

export interface SkillPreviewResponse {
  name: string;
  description: string;
  markdown: string;
  truncated: boolean;
  source: string;
  target_ids: string[];
}

export interface GitInspectionResponse {
  repository_url: string;
  requested_ref: string | null;
  commit: string;
  snapshot_id: string;
  candidates: Array<{
    id: string;
    type: "skill" | "mcp" | "plugin" | "package";
    title: string;
    description: string;
    relative_dir: string;
    repository_url: string;
    commit: string;
    snapshot_id: string;
    license: string;
    preview_id: string | null;
    manifest: Record<string, unknown> | null;
  }>;
}

export interface IntegrationGroupSummary {
  id: string;
  plan_id: string;
  status: string;
  component: string;
  source: string;
  catalog_id: string;
  catalog_ids?: { skill: string; mcp: string };
  package_id: string;
  package_version: string;
  target_mode: "all_supported";
  target_ids: string[];
  aggregate_risk: string;
  approval_hash: string | null;
  children: Array<{
    target_id: string;
    flow_id: string;
    status: string;
    verification_status: string;
    rollback_status: string;
    error_code: string | null;
  }>;
  repair_actions: string[];
  rollback_available: boolean;
  updated_at: string;
}

export interface IntegrationFlowSummary {
  id: string;
  plan_id: string;
  status: string;
  package_id: string;
  package_version: string;
  target_id: string;
  scope: string;
  verification_status: string;
  rollback_available: boolean;
  events: Array<{ stage: string; status: string; occurred_at: string; code: string | null }>;
}

export interface IntegrationFlowPlan {
  plan_id: string;
  package: {
    id: string;
    version: string;
    publisher: string;
    license: string;
    checksum: string;
    immutable_ref: string;
  };
  target: { id: string; scope: string; execution_owner: string; executable: boolean };
  risk: { decision: string; install_authorized: false };
  permissions: {
    network: boolean;
    native_consent: boolean;
    user_home: boolean;
    requirements: Array<{ id: string; type: string; reason: string }>;
  };
  configuration: { diff: string[]; restart_required: boolean; fields: string[] };
  verification_steps: string[];
  rollback_steps: string[];
  handoff_reason: string | null;
}

export interface IntegrationFlowPreviewResponse {
  flow: IntegrationFlowSummary;
  plan: IntegrationFlowPlan;
}

export interface IntegrationFlowMutationResponse {
  flow: IntegrationFlowSummary;
  handoff?: { owner: string; reason: string; mutation_performed: false };
}

export interface IntegrationGroupPlan {
  plan_id: string;
  package: { id: string; version: string; manifest_sha256: string };
  component: string;
  target_mode: "all_supported";
  target_ids: string[];
  aggregate_risk: string;
  permissions: { network: boolean; native_consent: boolean; user_home: boolean };
  children: Array<{
    target_id: string;
    scope: string;
    plan_id: string;
    configuration_diff: string[];
    restart_required: boolean;
    verification_steps: string[];
    rollback_steps: string[];
  }>;
  catalog_ids?: { skill: string; mcp: string };
  compatibility?: Array<{
    target: "codex" | "claude" | "gemini" | "harness";
    status: "supported" | "unsupported" | "unknown";
    included: boolean;
    components: {
      skill: {
        status: "supported" | "unsupported" | "unknown" | "not_applicable";
        target_id: string | null;
        reason_code: string | null;
        content_free: true;
      };
      mcp: {
        status: "supported" | "unsupported" | "unknown";
        target_id: string;
        reason_code: string | null;
        content_free: true;
      };
    };
  }>;
  atomicity: "recoverable_compensating_transaction";
}

export interface IntegrationGroupPreviewResponse {
  group: IntegrationGroupSummary;
  plan: IntegrationGroupPlan;
}

export interface IntegrationGroupMutationResponse {
  group: IntegrationGroupSummary;
}

export const remainingRequestKeys = {
  automation: () => [...rootKey, "automation"] as const,
  arena: (arenaId: string) => [...rootKey, "arena", arenaId] as const,
  arenaFiles: (query: string) => [...rootKey, "arena-files", query] as const,
  evaluation: () => [...rootKey, "evaluation"] as const,
  integrationFlows: () => [...rootKey, "integration-flows"] as const,
  mcpInventory: () => [...rootKey, "mcp-inventory"] as const,
};

export function arenaDetailOptions(arenaId: string) {
  return queryOptions({
    queryKey: remainingRequestKeys.arena(arenaId),
    queryFn: ({ signal }) =>
      fetchCockpit<ArenaProjectionResponse>(
        `/api/arena/runs/${encodeURIComponent(arenaId)}`,
        signal,
      ),
    staleTime: 2_000,
  });
}

export function arenaWorkspaceFilesOptions(query: string) {
  return queryOptions({
    queryKey: remainingRequestKeys.arenaFiles(query),
    queryFn: ({ signal }) =>
      fetchCockpit<ArenaWorkspaceFileSearchResponse>(
        withQuery("/api/workspace/tree", { workspace: ".", q: query, limit: 20 }),
        signal,
      ),
    staleTime: 10_000,
  });
}

export function automationSurfaceOptions() {
  return queryOptions({
    queryKey: remainingRequestKeys.automation(),
    queryFn: async ({ signal }) => {
      const [agents, workflows, schedules] = await Promise.all([
        fetchCockpit<unknown>("/api/agents", signal),
        fetchCockpit<unknown>("/api/workflows", signal),
        fetchCockpit<unknown>("/api/schedules", signal),
      ]);
      return projectAutomation(agents, workflows, schedules);
    },
    staleTime: 10_000,
  });
}

export function evaluationSurfaceOptions() {
  return queryOptions({
    queryKey: remainingRequestKeys.evaluation(),
    queryFn: async ({ signal }) => {
      const [evaluation, arenas] = await Promise.all([
        fetchCockpit<unknown>("/api/evaluate", signal),
        fetchCockpit<unknown>(withQuery("/api/arena/runs", { limit: 50 }), signal),
      ]);
      return projectEvaluation(evaluation, arenas);
    },
    staleTime: 10_000,
  });
}

export function mcpInventoryOptions() {
  return queryOptions({
    queryKey: remainingRequestKeys.mcpInventory(),
    queryFn: async ({ signal }) => projectMcpServers(
      await fetchCockpit<unknown>("/api/tool-servers", signal),
    ),
    staleTime: 15_000,
  });
}

export function integrationFlowOptions() {
  return queryOptions({
    queryKey: remainingRequestKeys.integrationFlows(),
    queryFn: ({ signal }) => fetchCockpit<IntegrationFlowInventory>("/api/integrations", signal),
    staleTime: 5_000,
  });
}
