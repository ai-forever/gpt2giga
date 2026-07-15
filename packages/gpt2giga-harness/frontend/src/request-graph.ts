import {
  queryOptions,
  type QueryClient,
  type QueryKey,
} from "@tanstack/react-query";

import {
  fetchCockpit,
  type RunOverviewResponse,
  type RunsCenterResponse,
  type SessionIndexResponse,
  type SessionOverviewResponse,
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
  runsCenter: () => [...rootKey, "runs-center"] as const,
  runScope: (runId: string) => [...rootKey, "run", runId] as const,
  runOverview: (runId: string) =>
    [...requestKeys.runScope(runId), "overview"] as const,
  runProjection: (runId: string, projection: RunProjection) =>
    [...requestKeys.runScope(runId), projection] as const,
};

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
