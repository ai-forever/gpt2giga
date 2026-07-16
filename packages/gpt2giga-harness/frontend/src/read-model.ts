import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import {
  cancelRequestScope,
  requestKeys,
  runOverviewOptions,
  runsCenterOptions,
  sessionIndexOptions,
  sessionOverviewOptions,
  sessionProjectionOptions,
} from "./request-graph";

export type ReadModelState = "idle" | "loading" | "ready" | "error";

export function useVisibleSessionReadModel(
  sessionId: string | undefined,
): ReadModelState {
  const queryClient = useQueryClient();
  const sessionIndex = useQuery(sessionIndexOptions());
  const overview = useQuery({
    ...sessionOverviewOptions(sessionId ?? "pending"),
    enabled: sessionId !== undefined,
  });
  const messages = useQuery({
    ...sessionProjectionOptions(sessionId ?? "pending", "messages"),
    enabled: sessionId !== undefined,
  });

  useEffect(() => {
    if (sessionId === undefined) return;
    const scope = requestKeys.sessionScope(sessionId);
    return () => {
      void cancelRequestScope(queryClient, scope);
    };
  }, [queryClient, sessionId]);

  return queryState(
    sessionIndex.isPending ||
      (sessionId !== undefined && (overview.isPending || messages.isPending)),
    sessionIndex.isError || overview.isError || messages.isError,
    sessionId === undefined ? sessionIndex.isSuccess : overview.isSuccess && messages.isSuccess,
  );
}

export function useVisibleRunReadModel(runId: string | undefined): ReadModelState {
  const queryClient = useQueryClient();
  const runs = useQuery(runsCenterOptions());
  const overview = useQuery({
    ...runOverviewOptions(runId ?? "pending"),
    enabled: runId !== undefined,
  });

  useEffect(() => {
    if (runId === undefined) return;
    const scope = requestKeys.runScope(runId);
    return () => {
      void cancelRequestScope(queryClient, scope);
    };
  }, [queryClient, runId]);

  return queryState(
    runs.isPending || (runId !== undefined && overview.isPending),
    runs.isError || overview.isError,
    runId === undefined ? runs.isSuccess : overview.isSuccess,
  );
}

function queryState(
  loading: boolean,
  error: boolean,
  ready: boolean,
): ReadModelState {
  if (error) return "error";
  if (loading) return "loading";
  if (ready) return "ready";
  return "idle";
}
