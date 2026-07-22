import type { EnvironmentResponse } from "./api";

const freshWindowMs = 60_000;

export type EnvironmentView = {
  branch: string;
  capturedAt: string;
  changes: string;
  commit: "blocked" | "ready";
  head: string;
  issuePr: string;
  push: string;
  status: "fresh" | "stale";
  worktree: string;
};

export function projectEnvironment(
  response: EnvironmentResponse,
  options: { failedRefresh?: boolean; now?: number } = {},
): EnvironmentView {
  const snapshot = response.environment;
  const captured = Date.parse(snapshot.captured_at);
  const now = options.now ?? Date.now();
  const stale =
    options.failedRefresh === true ||
    !Number.isFinite(captured) ||
    now - captured > freshWindowMs;
  return {
    branch: snapshot.branch ?? (snapshot.detached ? "detached" : "unknown"),
    capturedAt: snapshot.captured_at,
    changes: `${snapshot.staged_count} staged · ${snapshot.unstaged_count} unstaged · ${snapshot.untracked_count} untracked · +${snapshot.additions}/-${snapshot.deletions}`,
    commit: response.commit.ready ? "ready" : "blocked",
    head: snapshot.head?.slice(0, 8) ?? "unborn",
    issuePr: response.issue_pr.status,
    push: snapshot.push_ready ? "ready" : (snapshot.push_blocker ?? "blocked"),
    status: stale ? "stale" : "fresh",
    worktree: snapshot.worktree_root,
  };
}
