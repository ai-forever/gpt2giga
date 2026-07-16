import type {
  ArenaMessageProjection,
  ArenaProjectionResponse,
  HarnessOption,
  RunSummary,
  TokenUsageProjection,
} from "./api";
import type { RunStreamEvent } from "./stream-store";
import type { RunStreamStatus } from "./stream-store";
import { projectWorkbenchStream } from "./workbench-model";

export function arenaSelectionError(
  harnessIds: readonly string[],
  harnesses: readonly HarnessOption[],
  hasFiles: boolean,
): string | null {
  if (harnessIds.length < 2) return "Select at least two harnesses.";
  if (harnessIds.length > 4) return "Select no more than four harnesses.";
  const available = new Map(harnesses.map((item) => [item.spec.id, item]));
  for (const harnessId of harnessIds) {
    const harness = available.get(harnessId);
    if (harness === undefined || harness.availability?.status === "unavailable") {
      return `${harnessId} is unavailable.`;
    }
    if (hasFiles && harness.spec.supports_attachments !== true) {
      return `${harness.spec.title ?? harnessId} cannot receive shared files.`;
    }
  }
  return null;
}

export function projectArenaStream(
  messages: readonly ArenaMessageProjection[],
  events: readonly RunStreamEvent[],
  runId: string | undefined,
) {
  return projectWorkbenchStream(
    events,
    messages.map((item) => ({
      ...item,
      content: {
        text: item.content,
        byte_count: new TextEncoder().encode(item.content).byteLength,
        truncated: false,
      },
      usage: item.metadata?.usage,
    })),
    runId,
  );
}

export function arenaElapsedMs(
  run: RunSummary | undefined,
  now = Date.now(),
): number | null {
  const started = Date.parse(run?.started_at ?? run?.created_at ?? "");
  if (!Number.isFinite(started)) return null;
  const finished = Date.parse(run?.finished_at ?? "");
  const end = Number.isFinite(finished) ? finished : now;
  return Math.max(0, end - started);
}

export function arenaTokenUsage(
  messages: readonly ArenaMessageProjection[],
  streamUsage: TokenUsageProjection,
): TokenUsageProjection {
  const retained = [...messages]
    .reverse()
    .find((item) => item.role === "assistant" && item.metadata?.usage !== undefined)
    ?.metadata?.usage;
  return retained ?? streamUsage;
}

const activeArenaStatuses = new Set(["queued", "running", "retry_wait"]);

export function reconcileArenaTerminalEvent(
  response: ArenaProjectionResponse | undefined,
  childIndex: number,
  event: RunStreamEvent,
): ArenaProjectionResponse | undefined {
  if (response === undefined) return response;
  const child = response.arena.child_runs.find((item) => item.index === childIndex);
  const run = child?.runs?.at(-1) ?? child?.run;
  if (child === undefined || run?.id !== event.run_id) return response;
  const payloadStatus = event.payload?.status;
  const status = event.type === "run_canceled"
    ? "canceled"
    : typeof payloadStatus === "string"
      ? payloadStatus
      : child.status;
  const finishedAt = event.created_at ?? run.finished_at;
  const updateRun = (item: RunSummary): RunSummary =>
    item.id === event.run_id ? { ...item, finished_at: finishedAt, status } : item;
  const childRuns = response.arena.child_runs.map((item) =>
    item.index === childIndex
      ? {
          ...item,
          run: item.run === undefined ? undefined : updateRun(item.run),
          runs: item.runs?.map(updateRun),
          status,
        }
      : item,
  );
  const statuses = childRuns.map((item) => item.status);
  const arenaStatus = statuses.some((item) => activeArenaStatuses.has(item))
    ? "running"
    : statuses.every((item) => item === "succeeded")
      ? "succeeded"
      : statuses.every((item) => item === "canceled")
        ? "canceled"
        : statuses.some((item) => item === "succeeded")
          ? "partial"
          : "failed";
  return {
    arena: {
      ...response.arena,
      child_runs: childRuns,
      status: arenaStatus,
    },
  };
}

export function arenaTerminalStatus(event: RunStreamEvent | null): string | null {
  if (event === null) return null;
  if (event.type === "run_canceled") return "canceled";
  const status = event.payload?.status;
  return typeof status === "string" ? status : null;
}

export function arenaStatusFromChildren(statuses: readonly string[]): string {
  if (statuses.some((item) => activeArenaStatuses.has(item))) return "running";
  if (statuses.every((item) => item === "succeeded")) return "succeeded";
  if (statuses.every((item) => item === "canceled")) return "canceled";
  if (statuses.some((item) => item === "succeeded")) return "partial";
  return "failed";
}

export function arenaClosedStreamStatus(
  streamStatus: RunStreamStatus,
  events: readonly RunStreamEvent[],
  hasAssistantOutput: boolean,
): string | null {
  if (streamStatus !== "closed") return null;
  if (events.some((event) => event.type === "run_canceled")) return "canceled";
  if (events.some((event) => event.type === "error")) return "failed";
  return hasAssistantOutput ? "succeeded" : null;
}
