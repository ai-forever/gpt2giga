import type {
  ApprovalRequest,
  RunSummary,
  RunsCenterItem,
  SessionSummary,
} from "./api";

export type RunStage = "run" | "evidence" | "review" | "reuse";

const terminalStatuses = new Set(["succeeded", "failed", "canceled"]);

export function latestRun(runs: readonly RunSummary[]): RunSummary | null {
  return runs.at(-1) ?? null;
}

export function activeRun(run: RunSummary | null): boolean {
  return run !== null && !terminalStatuses.has(run.status);
}

export function runStage(run: RunSummary | null): RunStage {
  if (run === null || activeRun(run)) return "run";
  if ((run.artifacts?.length ?? 0) === 0) return "evidence";
  const hasReviewable = run.artifacts?.some((item) => item.type === "diff") ?? false;
  return hasReviewable ? "review" : "reuse";
}

export function pendingApproval(
  item: RunsCenterItem | null,
): ApprovalRequest | null {
  return item?.approvals.find((approval) => approval.status === "pending") ?? null;
}

export function sessionGroups(
  sessions: readonly SessionSummary[],
): ReadonlyArray<{ projectId: string; sessions: SessionSummary[] }> {
  const groups = new Map<string, SessionSummary[]>();
  for (const session of sessions) {
    const projectId = session.project_id || "unbound";
    const group = groups.get(projectId) ?? [];
    group.push(session);
    groups.set(projectId, group);
  }
  return [...groups.entries()].map(([projectId, items]) => ({
    projectId,
    sessions: items,
  }));
}

export function shortId(value: string | null | undefined): string {
  if (!value) return "—";
  return value.length > 12 ? value.slice(-8) : value;
}

export function formatDuration(milliseconds: number | null): string {
  if (milliseconds === null || !Number.isFinite(milliseconds)) return "—";
  if (milliseconds < 1_000) return `${Math.max(0, Math.round(milliseconds))} ms`;
  const seconds = Math.round(milliseconds / 1_000);
  if (seconds < 60) return `${seconds} s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ${seconds % 60}s`;
}

export function formatTimestamp(value: string | null | undefined, locale: string): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return value;
  return new Intl.DateTimeFormat(locale, {
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    month: "short",
  }).format(date);
}

export function statusTone(status: string): "success" | "warning" | "danger" | "neutral" {
  if (["completed", "succeeded", "approved", "ready"].includes(status)) return "success";
  if (["failed", "error", "denied", "canceled"].includes(status)) return "danger";
  if (["approval-needed", "waiting_approval", "blocked", "attention"].includes(status)) {
    return "warning";
  }
  return "neutral";
}
