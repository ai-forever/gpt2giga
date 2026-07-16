import { describe, expect, it } from "vitest";

import type { MessageProjection, RunSummary } from "./api";
import type { RunStreamEvent } from "./stream-store";
import { projectWorkbenchStream, workbenchRunActive } from "./workbench-model";

function event(id: string, type: string, delta?: string): RunStreamEvent {
  return {
    id,
    payload: delta === undefined ? {} : { delta },
    run_id: "run-one",
    type,
  };
}

function run(status: string): RunSummary {
  return {
    id: "run-one",
    session_id: "session-one",
    status,
    updated_at: "2026-07-16T00:00:00Z",
  };
}

describe("workbench presentation model", () => {
  it("keeps lifecycle events out of chat while preserving live assistant text and files", () => {
    const finished = event("finished", "run_finished");
    const projected = projectWorkbenchStream(
      [
        event("started", "run_started"),
        event("raw", "raw_request"),
        event("delta-one", "message_delta", "Hello "),
        event("thread", "external_thread_status"),
        event("delta-two", "message_delta", "world"),
        event("file", "generated_file"),
        finished,
      ],
      [],
      "run-one",
    );

    expect(projected.assistantText).toBe("Hello world");
    expect(projected.generatedFiles.map((item) => item.id)).toEqual(["file"]);
    expect(projected.terminalEvent).toBe(finished);
  });

  it("hides a live delta after the retained response becomes authoritative", () => {
    const messages: MessageProjection[] = [
      {
        content: { byte_count: 5, text: "Hello", truncated: false },
        created_at: "2026-07-16T00:00:00Z",
        id: "message-one",
        role: "assistant",
        run_id: "run-one",
      },
    ];

    expect(
      projectWorkbenchStream(
        [event("delta", "message_delta", "Hello")],
        messages,
        "run-one",
      ).assistantText,
    ).toBe("");
  });

  it("lets a terminal event override a stale running summary", () => {
    expect(workbenchRunActive(run("running"), "run-one", "run-one", null)).toBe(true);
    expect(
      workbenchRunActive(
        run("running"),
        "run-one",
        "run-one",
        event("finished", "run_finished"),
      ),
    ).toBe(false);
    expect(workbenchRunActive(run("succeeded"), "run-one", undefined, null)).toBe(false);
  });

  it("projects tool activity and keeps update_plan out of raw chat", () => {
    const projection = projectWorkbenchStream(
      [
        {
          id: "tool-one",
          payload: {
            arguments: { path: "src/app.ts" },
            name: "read_file",
            status: "completed",
            tool_call_id: "call-one",
          },
          run_id: "run-one",
          type: "tool_call_finished",
        },
        {
          id: "plan-one",
          payload: {
            arguments: {
              plan: [
                { status: "completed", step: "Inspect stream" },
                { status: "in_progress", step: "Render tools" },
              ],
            },
            name: "update_plan",
            status: "completed",
            tool_call_id: "call-plan",
          },
          run_id: "run-one",
          type: "tool_call_finished",
        },
      ],
      [],
      "run-one",
    );

    expect(projection.toolActivities).toEqual([
      {
        id: "call-one",
        label: "Reading src/app.ts",
        name: "read_file",
        status: "completed",
      },
    ]);
    expect(projection.plan.map((item) => item.step)).toEqual([
      "Inspect stream",
      "Render tools",
    ]);
  });
});
