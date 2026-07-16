import {
  queryOptions,
  type QueryClient,
  type QueryKey,
} from "@tanstack/react-query";

import {
  type ApprovalInboxResponse,
  type AttachmentsResponse,
  type AttentionInboxResponse,
  fetchCockpit,
  type HarnessesResponse,
  type ModelsResponse,
  type RunCenterSummaryResponse,
  type RunOverviewResponse,
  type RunTraceResponse,
  type RunsCenterResponse,
  type SessionIndexResponse,
  type SessionEventsResponse,
  type SessionMessagesResponse,
  type SessionOverviewResponse,
  type SessionRunsResponse,
  type SettingsResponse,
  type WorkspaceFileSearchResponse,
  withQuery,
} from "./api";

export type SessionProjection = "messages" | "runs" | "events" | "artifacts";
export type RunProjection = "raw" | "diff" | "report";

const rootKey = ["cockpit"] as const;

export const requestKeys = {
  root: rootKey,
  sessionIndex: () => [...rootKey, "session-index"] as const,
  sessionScope: (sessionId: string) =>
    [...rootKey, "session", sessionId] as const,
  sessionOverview: (sessionId: string) =>
    [...requestKeys.sessionScope(sessionId), "overview"] as const,
  sessionProjection: (sessionId: string, projection: SessionProjection) =>
    [...requestKeys.sessionScope(sessionId), projection] as const,
  sessionAttachments: (sessionId: string) =>
    [...requestKeys.sessionScope(sessionId), "attachments"] as const,
  workspaceFiles: (sessionId: string, query: string) =>
    [...requestKeys.sessionScope(sessionId), "workspace-files", query] as const,
  harnesses: () => [...rootKey, "harnesses"] as const,
  models: (apiMode: string) => [...rootKey, "models", apiMode] as const,
  settings: () => [...rootKey, "settings"] as const,
  runsCenter: () => [...rootKey, "runs-center"] as const,
  approvals: () => [...rootKey, "approvals"] as const,
  attention: () => [...rootKey, "attention"] as const,
  runScope: (runId: string) => [...rootKey, "run", runId] as const,
  runOverview: (runId: string) =>
    [...requestKeys.runScope(runId), "overview"] as const,
  runCenterSummary: (runId: string) =>
    [...requestKeys.runScope(runId), "center-summary"] as const,
  runTrace: (runId: string) =>
    [...requestKeys.runScope(runId), "trace"] as const,
  runProjection: (runId: string, projection: RunProjection) =>
    [...requestKeys.runScope(runId), projection] as const,
};

export function harnessesOptions() {
  return queryOptions({
    queryKey: requestKeys.harnesses(),
    queryFn: ({ signal }) => fetchCockpit<HarnessesResponse>("/api/harnesses", signal),
    staleTime: 30_000,
  });
}

export function modelsOptions(apiMode: string) {
  return queryOptions({
    queryKey: requestKeys.models(apiMode),
    queryFn: ({ signal }) =>
      fetchCockpit<ModelsResponse>(withQuery("/api/models", { api_mode: apiMode }), signal),
    staleTime: 30_000,
  });
}

export function settingsOptions() {
  return queryOptions({
    queryKey: requestKeys.settings(),
    queryFn: ({ signal }) => fetchCockpit<SettingsResponse>("/api/settings", signal),
    staleTime: 10_000,
  });
}

export function sessionAttachmentsOptions(sessionId: string) {
  return queryOptions({
    queryKey: requestKeys.sessionAttachments(sessionId),
    queryFn: ({ signal }) =>
      fetchCockpit<AttachmentsResponse>(
        `/api/sessions/${encodeURIComponent(sessionId)}/attachments`,
        signal,
      ),
    staleTime: 5_000,
  });
}

export function workspaceFilesOptions(sessionId: string, query: string) {
  return queryOptions({
    queryKey: requestKeys.workspaceFiles(sessionId, query),
    queryFn: ({ signal }) =>
      fetchCockpit<WorkspaceFileSearchResponse>(
        withQuery(
          `/api/sessions/${encodeURIComponent(sessionId)}/attachments/workspace/search`,
          { q: query, limit: 20 },
        ),
        signal,
      ),
    staleTime: 10_000,
  });
}

export function sessionIndexOptions() {
  return queryOptions({
    queryKey: requestKeys.sessionIndex(),
    queryFn: ({ signal }) =>
      fetchCockpit<SessionIndexResponse>(
        withQuery("/api/cockpit/sessions", { limit: 50 }),
        signal,
      ),
    staleTime: 15_000,
  });
}

export function sessionOverviewOptions(sessionId: string) {
  return queryOptions({
    queryKey: requestKeys.sessionOverview(sessionId),
    queryFn: ({ signal }) =>
      fetchCockpit<SessionOverviewResponse>(
        `/api/cockpit/sessions/${encodeURIComponent(sessionId)}`,
        signal,
      ),
    staleTime: 10_000,
  });
}

export function sessionProjectionOptions(
  sessionId: string,
  projection: SessionProjection,
) {
  return queryOptions({
    queryKey: requestKeys.sessionProjection(sessionId, projection),
    queryFn: ({ signal }) =>
      fetchCockpit<Record<string, unknown>>(
        withQuery(
          `/api/cockpit/sessions/${encodeURIComponent(sessionId)}/${projection}`,
          { limit: projection === "events" ? 100 : 50 },
        ),
        signal,
      ),
    staleTime: 5_000,
  });
}

export function sessionMessagesOptions(sessionId: string) {
  return queryOptions({
    queryKey: requestKeys.sessionProjection(sessionId, "messages"),
    queryFn: ({ signal }) =>
      fetchCockpit<SessionMessagesResponse>(
        withQuery(
          `/api/cockpit/sessions/${encodeURIComponent(sessionId)}/messages`,
          { limit: 50 },
        ),
        signal,
      ),
    staleTime: 5_000,
  });
}

export function sessionRunsOptions(sessionId: string) {
  return queryOptions({
    queryKey: requestKeys.sessionProjection(sessionId, "runs"),
    queryFn: ({ signal }) =>
      fetchCockpit<SessionRunsResponse>(
        withQuery(
          `/api/cockpit/sessions/${encodeURIComponent(sessionId)}/runs`,
          { limit: 50 },
        ),
        signal,
      ),
    staleTime: 5_000,
  });
}

export function sessionEventsOptions(sessionId: string) {
  return queryOptions({
    queryKey: requestKeys.sessionProjection(sessionId, "events"),
    queryFn: ({ signal }) =>
      fetchCockpit<SessionEventsResponse>(
        withQuery(
          `/api/cockpit/sessions/${encodeURIComponent(sessionId)}/events`,
          { limit: 100 },
        ),
        signal,
      ),
    staleTime: 5_000,
  });
}

export function runsCenterOptions() {
  return queryOptions({
    queryKey: requestKeys.runsCenter(),
    queryFn: ({ signal }) =>
      fetchCockpit<RunsCenterResponse>(
        withQuery("/api/runs", { limit: 25 }),
        signal,
      ),
    staleTime: 5_000,
  });
}

export function runOverviewOptions(runId: string) {
  return queryOptions({
    queryKey: requestKeys.runOverview(runId),
    queryFn: ({ signal }) =>
      fetchCockpit<RunOverviewResponse>(
        `/api/cockpit/runs/${encodeURIComponent(runId)}`,
        signal,
      ),
    staleTime: 5_000,
  });
}

export function runCenterSummaryOptions(runId: string) {
  return queryOptions({
    queryKey: requestKeys.runCenterSummary(runId),
    queryFn: ({ signal }) =>
      fetchCockpit<RunCenterSummaryResponse>(
        `/api/runs/${encodeURIComponent(runId)}/summary`,
        signal,
      ),
    staleTime: 5_000,
  });
}

export function runTraceOptions(runId: string) {
  return queryOptions({
    queryKey: requestKeys.runTrace(runId),
    queryFn: ({ signal }) =>
      fetchCockpit<RunTraceResponse>(
        withQuery(`/api/runs/${encodeURIComponent(runId)}/trace`, { limit: 200 }),
        signal,
      ),
    staleTime: 2_000,
  });
}

export function approvalsOptions() {
  return queryOptions({
    queryKey: requestKeys.approvals(),
    queryFn: ({ signal }) =>
      fetchCockpit<ApprovalInboxResponse>(
        withQuery("/api/approvals", { limit: 100 }),
        signal,
      ),
    staleTime: 5_000,
  });
}

export function attentionOptions() {
  return queryOptions({
    queryKey: requestKeys.attention(),
    queryFn: ({ signal }) =>
      fetchCockpit<AttentionInboxResponse>("/api/attention", signal),
    staleTime: 5_000,
  });
}

export function runProjectionOptions(runId: string, projection: RunProjection) {
  return queryOptions({
    queryKey: requestKeys.runProjection(runId, projection),
    queryFn: ({ signal }) =>
      fetchCockpit<Record<string, unknown>>(
        `/api/cockpit/runs/${encodeURIComponent(runId)}/${projection}`,
        signal,
      ),
    staleTime: 30_000,
  });
}

export function cancelRequestScope(
  queryClient: QueryClient,
  scope: QueryKey,
): Promise<void> {
  return queryClient.cancelQueries({ queryKey: scope });
}

export async function refreshSessionAfterRunStart(
  queryClient: QueryClient,
  sessionId: string,
): Promise<void> {
  await Promise.all([
    queryClient.invalidateQueries({
      queryKey: requestKeys.sessionProjection(sessionId, "messages"),
    }),
    queryClient.invalidateQueries({ queryKey: requestKeys.runsCenter() }),
  ]);
}

export async function refreshSessionRevision(
  queryClient: QueryClient,
  sessionId: string,
): Promise<void> {
  await Promise.all([
    queryClient.invalidateQueries({
      queryKey: requestKeys.sessionOverview(sessionId),
    }),
    queryClient.invalidateQueries({ queryKey: requestKeys.sessionIndex() }),
  ]);
}

export function updateSessionOverview(
  queryClient: QueryClient,
  sessionId: string,
  update: (current: SessionOverviewResponse) => SessionOverviewResponse,
): void {
  queryClient.setQueryData<SessionOverviewResponse>(
    requestKeys.sessionOverview(sessionId),
    (current) => (current === undefined ? current : update(current)),
  );
}

export function updateRunOverview(
  queryClient: QueryClient,
  runId: string,
  update: (current: RunOverviewResponse) => RunOverviewResponse,
): void {
  queryClient.setQueryData<RunOverviewResponse>(
    requestKeys.runOverview(runId),
    (current) => (current === undefined ? current : update(current)),
  );
}
