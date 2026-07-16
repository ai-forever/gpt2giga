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
  projectIntegrations,
} from "./surface-projections";

const rootKey = ["cockpit", "remaining-surfaces"] as const;

export const remainingRequestKeys = {
  automation: () => [...rootKey, "automation"] as const,
  arena: (arenaId: string) => [...rootKey, "arena", arenaId] as const,
  arenaFiles: (query: string) => [...rootKey, "arena-files", query] as const,
  evaluation: () => [...rootKey, "evaluation"] as const,
  integrations: () => [...rootKey, "integrations"] as const,
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

export function integrationsSurfaceOptions() {
  return queryOptions({
    queryKey: remainingRequestKeys.integrations(),
    queryFn: async ({ signal }) => {
      const [harnesses, settings, modelsV1, modelsV2, mcp] = await Promise.all([
        fetchCockpit<unknown>("/api/harnesses", signal),
        fetchCockpit<unknown>("/api/settings", signal),
        fetchCockpit<unknown>(withQuery("/api/models", { api_mode: "v1" }), signal),
        fetchCockpit<unknown>(withQuery("/api/models", { api_mode: "v2" }), signal),
        fetchCockpit<unknown>("/api/tool-servers", signal),
      ]);
      return projectIntegrations(harnesses, settings, [modelsV1, modelsV2], mcp);
    },
    staleTime: 15_000,
  });
}
