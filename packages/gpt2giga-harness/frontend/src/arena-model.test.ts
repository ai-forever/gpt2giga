import { describe, expect, it } from "vitest";

import type { ArenaMessageProjection, HarnessOption } from "./api";
import {
  arenaElapsedMs,
  arenaClosedStreamStatus,
  arenaSelectionError,
  arenaStatusFromChildren,
  arenaTerminalStatus,
  arenaTokenUsage,
  projectArenaStream,
  reconcileArenaTerminalEvent,
} from "./arena-model";

const harnesses: HarnessOption[] = [
  { spec: { id: "a", title: "A", supports_attachments: true }, availability: { status: "available" } },
  { spec: { id: "b", title: "B", supports_attachments: false }, availability: { status: "available" } },
];

describe("Arena model", () => {
  it("requires two to four truthful harness selections", () => {
    expect(arenaSelectionError(["a"], harnesses, false)).toContain("two");
    expect(arenaSelectionError(["a", "b"], harnesses, true)).toContain("cannot receive");
    expect(arenaSelectionError(["a", "b"], harnesses, false)).toBeNull();
  });

  it("projects independent streaming text without duplicating retained output", () => {
    const events = [
      { id: "1", run_id: "run-a", type: "message_delta", payload: { delta: "Hel" } },
      { id: "2", run_id: "run-b", type: "message_delta", payload: { delta: "Other" } },
      { id: "3", run_id: "run-a", type: "message_delta", payload: { delta: "lo" } },
    ];
    expect(projectArenaStream([], events, "run-a").assistantText).toBe("Hello");
    const retained: ArenaMessageProjection[] = [
      { id: "m", run_id: "run-a", role: "assistant", content: "Done", created_at: "now" },
    ];
    expect(projectArenaStream(retained, events, "run-a").assistantText).toBe("");
  });

  it("uses terminal elapsed time and retained token usage", () => {
    expect(arenaElapsedMs({ id: "r", session_id: "s", status: "succeeded", updated_at: "", started_at: "2026-01-01T00:00:00Z", finished_at: "2026-01-01T00:00:02Z" })).toBe(2000);
    expect(arenaTokenUsage([
      { id: "m", role: "assistant", content: "ok", created_at: "now", metadata: { usage: { total_tokens: 12 } } },
    ], { total_tokens: 3 })).toEqual({ total_tokens: 12 });
  });

  it("reconciles simultaneous terminal events without waiting for a refetch", () => {
    const base = {
      arena: {
        id: "arena",
        session_id: "parent",
        status: "running",
        prompt: "compare",
        harness_ids: ["a", "b"],
        model: null,
        api_mode: "v2",
        mode: "plan",
        workspace: ".",
        attachment_ids: [],
        created_at: "now",
        updated_at: "now",
        metadata: {},
        child_runs: [
          { harness_id: "a", index: 0, session_id: "sa", run_id: "ra", status: "running", run: { id: "ra", session_id: "sa", status: "running", updated_at: "now" } },
          { harness_id: "b", index: 1, session_id: "sb", run_id: "rb", status: "running", run: { id: "rb", session_id: "sb", status: "running", updated_at: "now" } },
        ],
      },
    };
    const first = reconcileArenaTerminalEvent(base, 0, {
      id: "ea",
      run_id: "ra",
      type: "run_finished",
      payload: { status: "succeeded" },
    });
    expect(first?.arena.child_runs.map((item) => item.status)).toEqual(["succeeded", "running"]);
    expect(first?.arena.status).toBe("running");
    const finished = reconcileArenaTerminalEvent(first, 1, {
      id: "eb",
      run_id: "rb",
      type: "run_finished",
      payload: { status: "succeeded" },
    });
    expect(finished?.arena.child_runs.map((item) => item.status)).toEqual(["succeeded", "succeeded"]);
    expect(finished?.arena.status).toBe("succeeded");
  });

  it("derives child and parent presentation status from terminal streams", () => {
    expect(arenaTerminalStatus({
      id: "done",
      run_id: "run",
      type: "run_finished",
      payload: { status: "succeeded" },
    })).toBe("succeeded");
    expect(arenaTerminalStatus({ id: "stop", run_id: "run", type: "run_canceled" })).toBe("canceled");
    expect(arenaStatusFromChildren(["succeeded", "running"])).toBe("running");
    expect(arenaStatusFromChildren(["succeeded", "failed"])).toBe("partial");
    expect(arenaStatusFromChildren(["succeeded", "succeeded"])).toBe("succeeded");
    expect(arenaClosedStreamStatus("live", [], true)).toBeNull();
    expect(arenaClosedStreamStatus("closed", [], true)).toBe("succeeded");
    expect(arenaClosedStreamStatus("closed", [{ id: "e", run_id: "run", type: "error" }], true)).toBe("failed");
  });
});
