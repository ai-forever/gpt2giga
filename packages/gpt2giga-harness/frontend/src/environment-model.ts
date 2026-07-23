import type { EnvironmentResponse } from "./api";

const freshWindowMs = 60_000;

export type EnvironmentView = {
  branch: string;
  capturedAt: string;
  changes: string;
  commit: "blocked" | "ready";
  githubActions: string;
  githubChecks: string;
  githubRepository: string;
  githubStatus: string;
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
  const pullRequest = response.github.pull_request;
  const latestRun = response.github.runs[0];
  return {
    branch: snapshot.branch ?? (snapshot.detached ? "detached" : "unknown"),
    capturedAt: snapshot.captured_at,
    changes: `${snapshot.staged_count} staged · ${snapshot.unstaged_count} unstaged · ${snapshot.untracked_count} untracked · +${snapshot.additions}/-${snapshot.deletions}`,
    commit: response.commit.ready ? "ready" : "blocked",
    githubActions: latestRun === undefined
      ? "unavailable"
      : `${latestRun.conclusion ?? latestRun.status} · ${response.github.runs.length} run${response.github.runs.length === 1 ? "" : "s"} · ${latestRun.jobs.status} jobs`,
    githubChecks: pullRequest?.checks.status ?? "unavailable",
    githubRepository: response.github.repository?.name_with_owner ?? "not connected",
    githubStatus: response.github.status,
    head: snapshot.head?.slice(0, 8) ?? "unborn",
    issuePr: pullRequest === null
      ? response.issue_pr.status
      : `PR #${pullRequest.number} ${pullRequest.state}${pullRequest.draft ? " draft" : ""}`,
    push: snapshot.push_ready ? "ready" : (snapshot.push_blocker ?? "blocked"),
    status: stale ? "stale" : "fresh",
    worktree: snapshot.worktree_root,
  };
}
