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
  freshness: { captured_at: "2026-07-22T10:00:00Z", status: "fresh" },
  issue_pr: { status: "not_connected" },
};

describe("projectEnvironment", () => {
  it("renders the bounded environment and readiness fields", () => {
    expect(projectEnvironment(response, { now: Date.parse("2026-07-22T10:00:30Z") })).toEqual({
      branch: "feature/environment",
      capturedAt: "2026-07-22T10:00:00Z",
      changes: "1 staged · 2 unstaged · 3 untracked · +12/-3",
      commit: "ready",
      head: "aaaaaaaa",
      issuePr: "not_connected",
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
