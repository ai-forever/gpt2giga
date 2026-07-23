import { describe, expect, it } from "vitest";

import type { EnvironmentResponse } from "./api";
import { projectEnvironment } from "./environment-model";

const response: EnvironmentResponse = {
  commit: { blocker: null, ready: true },
  environment: {
    additions: 12,
    ahead: 1,
    base_identity: "b".repeat(40),
    behind: 0,
    branch: "feature/environment",
    captured_at: "2026-07-22T10:00:00Z",
    changed_paths: ["src/app.tsx"],
    changed_paths_truncated: false,
    deletions: 3,
    detached: false,
    diff_sha256: "d".repeat(64),
    head: "a".repeat(40),
    provider_id: "git",
    push_blocker: null,
    push_ready: true,
    remote: "origin",
    repository_root: "/repo",
    schema_version: 1,
    staged_count: 1,
    unstaged_count: 2,
    untracked_count: 3,
    upstream: "origin/feature/environment",
    worktree_root: "/repo/worktree",
  },
  github: {
    schema_version: 1,
    status: "ready",
    auth_status: "authenticated",
    checked_at: "2026-07-22T10:00:01Z",
    repository: {
      host: "github.com",
      name_with_owner: "ferriscorp/gigalo",
      url: "https://github.com/ferriscorp/gigalo",
      default_branch: "main",
      is_fork: false,
    },
    pull_request: {
      number: 164,
      state: "open",
      url: "https://github.com/ferriscorp/gigalo/pull/164",
      draft: false,
      head_branch: "feature/environment",
      base_branch: "main",
      checks: { status: "passed", total: 2, passed: 2, failed: 0, pending: 0, skipped: 0, cancelled: 0, unknown: 0 },
      issues: [{ number: 77, state: "open", url: "https://github.com/ferriscorp/gigalo/issues/77" }],
    },
    runs: [{
      database_id: 123,
      status: "completed",
      conclusion: "success",
      url: "https://github.com/ferriscorp/gigalo/actions/runs/123",
      head_sha: "a".repeat(40),
      created_at: "2026-07-22T09:55:00Z",
      updated_at: "2026-07-22T09:59:00Z",
      jobs: { status: "passed", total: 3, passed: 3, failed: 0, pending: 0, skipped: 0, cancelled: 0, unknown: 0 },
    }],
    reason_code: null,
    cached: false,
    stale: false,
  },
  freshness: { captured_at: "2026-07-22T10:00:00Z", status: "fresh" },
  issue_pr: { status: "open", kind: "pull_request", number: 164 },
};

describe("projectEnvironment", () => {
  it("renders the bounded environment and readiness fields", () => {
    expect(projectEnvironment(response, { now: Date.parse("2026-07-22T10:00:30Z") })).toEqual({
      branch: "feature/environment",
      capturedAt: "2026-07-22T10:00:00Z",
      changes: "1 staged · 2 unstaged · 3 untracked · +12/-3",
      commit: "ready",
      githubActions: "success · 1 run · passed jobs",
      githubChecks: "passed",
      githubRepository: "ferriscorp/gigalo",
      githubStatus: "ready",
      head: "aaaaaaaa",
      issuePr: "PR #164 open",
      push: "ready",
      status: "fresh",
      worktree: "/repo/worktree",
    });
  });

  it("marks retained data stale after age or a failed refresh", () => {
    expect(projectEnvironment(response, { now: Date.parse("2026-07-22T10:01:01Z") }).status).toBe("stale");
    expect(projectEnvironment(response, { failedRefresh: true }).status).toBe("stale");
  });
});
