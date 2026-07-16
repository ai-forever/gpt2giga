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

  it("projects reasoning, usage, and an inspectable tool result", () => {
    const projection = projectWorkbenchStream(
      [
        {
          id: "reasoning",
          payload: { delta: "Checking context", kind: "summary" },
          run_id: "run-one",
          type: "reasoning_delta",
        },
        {
          id: "tool",
          payload: {
            name: "shell",
            result: "file-one\nfile-two",
            status: "completed",
            tool_call_id: "call-shell",
          },
          run_id: "run-one",
          type: "tool_call_finished",
        },
        {
          id: "usage",
          payload: { input_tokens: 21, output_tokens: 8, source: "ignored" },
          run_id: "run-one",
          type: "usage",
        },
      ],
      [],
      "run-one",
    );

    expect(projection.reasoningText).toBe("Checking context");
    expect(projection.usage).toEqual({ input_tokens: 21, output_tokens: 8 });
    expect(projection.toolActivities[0]?.result).toBe("file-one\nfile-two");
  });

  it("nests subagent tools under invoke_agent and keeps their final results", () => {
    const projection = projectWorkbenchStream(
      [
        {
          id: "agent-start",
          payload: {
            arguments: { agent_name: "investigator" },
            name: "invoke_agent",
            status: "running",
            tool_call_id: "agent-call",
          },
          run_id: "run-one",
          type: "tool_call_started",
        },
        {
          id: "child-start",
          payload: {
            arguments: { command: "rg TODO" },
            name: "shell",
            parent_tool_call_id: "agent-call",
            status: "running",
            tool_call_id: "child-call",
          },
          run_id: "run-one",
          type: "tool_call_started",
        },
        {
          id: "child-finish",
          payload: {
            name: "shell",
            parent_tool_call_id: "agent-call",
            result: "src/app.py:10: TODO",
            status: "completed",
            tool_call_id: "child-call",
          },
          run_id: "run-one",
          type: "tool_call_finished",
        },
        {
          id: "agent-finish",
          payload: {
            name: "invoke_agent",
            result: "Repository inspected.",
            status: "completed",
            tool_call_id: "agent-call",
          },
          run_id: "run-one",
          type: "tool_call_finished",
        },
      ],
      [],
      "run-one",
    );

    expect(projection.toolActivities).toHaveLength(1);
    expect(projection.toolActivities[0]).toMatchObject({
      id: "agent-call",
      name: "invoke_agent",
      result: "Repository inspected.",
      status: "completed",
    });
    expect(projection.toolActivities[0]?.children).toEqual([
      expect.objectContaining({
        id: "child-call",
        name: "shell",
        parentId: "agent-call",
        result: "src/app.py:10: TODO",
        status: "completed",
      }),
    ]);
  });

  it("labels Codex subagents with their name, role, task, and nested tools", () => {
    const projection = projectWorkbenchStream(
      [
        {
          id: "spawn-finish",
          payload: {
            arguments: {
              prompt: "Inspect repository configuration",
              subagents: [
                { id: "thread-child", name: "Hypatia", role: "explorer" },
              ],
            },
            name: "spawn_agent",
            status: "completed",
            tool_call_id: "spawn-1",
          },
          run_id: "run-one",
          type: "tool_call_finished",
        },
        {
          id: "child-finish",
          payload: {
            arguments: { command: "rg --files" },
            name: "shell",
            parent_tool_call_id: "spawn-1",
            result: "pyproject.toml",
            status: "completed",
            tool_call_id: "thread-child:command-1",
          },
          run_id: "run-one",
          type: "tool_call_finished",
        },
      ],
      [],
      "run-one",
    );

    expect(projection.toolActivities).toEqual([
      expect.objectContaining({
        detail: "explorer · Inspect repository configuration",
        id: "spawn-1",
        label: "Subagent Hypatia",
        name: "spawn_agent",
        children: [
          expect.objectContaining({
            id: "thread-child:command-1",
            name: "shell",
            parentId: "spawn-1",
          }),
        ],
      }),
    ]);
  });
});
