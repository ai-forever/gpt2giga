import { describe, expect, it } from "vitest";

import type { RunSummary, SessionSummary } from "./api";
import {
  activeRun,
  formatDuration,
  latestRun,
  runStage,
  sessionGroups,
  shortId,
  statusTone,
} from "./surface-model";

function run(status: string, artifacts: RunSummary["artifacts"] = []): RunSummary {
  return {
    artifacts,
    id: `run-${status}`,
    session_id: "session",
    status,
    updated_at: "2026-07-16T00:00:00Z",
  };
}

describe("Cockpit vertical surface model", () => {
  it("keeps the newest append-order run and derives explicit progression", () => {
    const running = run("running");
    const reviewable = run("succeeded", [{ type: "diff" }]);

    expect(latestRun([running, reviewable])).toBe(reviewable);
    expect(activeRun(running)).toBe(true);
    expect(runStage(running)).toBe("run");
    expect(runStage(run("succeeded"))).toBe("evidence");
    expect(runStage(reviewable)).toBe("review");
    expect(runStage(run("succeeded", [{ type: "report" }]))).toBe("reuse");
  });

  it("groups bounded session summaries by stable project identity", () => {
    const sessions: SessionSummary[] = [
      { archived: false, id: "one", pinned: false, project_id: "alpha", title: "One", updated_at: "1" },
      { archived: false, id: "two", pinned: false, project_id: null, title: "Two", updated_at: "2" },
      { archived: false, id: "three", pinned: false, project_id: "alpha", title: "Three", updated_at: "3" },
    ];

    expect(sessionGroups(sessions)).toEqual([
      { projectId: "alpha", sessions: [sessions[0], sessions[2]] },
      { projectId: "unbound", sessions: [sessions[1]] },
    ]);
  });

  it("formats bounded operational labels without exposing full identities", () => {
    expect(shortId("run_123456789abcdef")).toBe("89abcdef");
    expect(formatDuration(62_000)).toBe("1m 2s");
    expect(statusTone("approval-needed")).toBe("warning");
    expect(statusTone("failed")).toBe("danger");
  });
});
