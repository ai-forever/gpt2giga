import { describe, expect, it } from "vitest";

import type { HarnessOption } from "./api";
import {
  activeAtQuery,
  availableExecutionTransports,
  capabilityPresentation,
  consumeAtQuery,
  invocationModeForTransport,
  normalizeExecutionSelection,
  permissionSimulationHighlights,
} from "./workbench-execution";

function harness(overrides: Partial<HarnessOption> = {}): HarnessOption {
  return {
    spec: {
      id: "codex-cli",
      capabilities: ["agent_cli"],
      supports_native_sessions: true,
    },
    compatibility: { compatible: true },
    workbench_transport: {
      default: "native_structured",
      options: [
        { id: "native_structured", status: "ready", detail: "structured", durable: true, provider_native_continuity: true },
        { id: "native_terminal", status: "ready", detail: "terminal", durable: false, provider_native_continuity: false },
        { id: "one_shot", status: "ready", detail: "one shot", durable: false, provider_native_continuity: false },
      ],
    },
    ...overrides,
  };
}

describe("Workbench execution semantics", () => {
  it("projects canonical structured, terminal, and one-shot transports", () => {
    expect(availableExecutionTransports(harness())).toEqual([
      "native_structured",
      "native_terminal",
      "one_shot",
    ]);
    expect(availableExecutionTransports(harness({
      spec: { id: "direct-chat", capabilities: ["chat_completions"] },
      workbench_transport: {
        default: "one_shot",
        options: [{ id: "one_shot", status: "ready", detail: "one shot", durable: false, provider_native_continuity: false }],
      },
    }))).toEqual(["one_shot"]);
  });

  it("normalizes stale invocation and capability after a harness change", () => {
    expect(normalizeExecutionSelection(
      harness({
        spec: { id: "direct-chat", capabilities: ["chat_completions"] },
        workbench_transport: {
          default: "one_shot",
          options: [{ id: "one_shot", status: "ready", detail: "one shot", durable: false, provider_native_continuity: false }],
        },
      }),
      { capability: "agent_cli", executionTransport: "native_terminal" },
    )).toEqual({ capability: "chat_completions", executionTransport: "one_shot" });
    expect(invocationModeForTransport("native_terminal")).toBe("native");
    expect(invocationModeForTransport("native_structured")).toBe("headless");
  });

  it("presents capabilities as operator concepts", () => {
    expect(capabilityPresentation("agent_cli").label).toBe("Coding agent");
    expect(capabilityPresentation("chat_completions").label).toBe("Direct chat");
  });

  it("summarizes content-free permission evidence without hiding unknowns", () => {
    expect(permissionSimulationHighlights({
      approval_points: ["mcp.tool.call"],
      block_run: false,
      blocked_actions: [],
      content_free: true,
      outcomes: [],
      provider_safety_proven: false,
      route_snapshot: {
        execution_transport: "native_structured",
        extension_count: 1,
        harness_id: "codex-cli",
        snapshot_hash: "b".repeat(64),
      },
      side_effect_free: true,
      simulation_hash: "a".repeat(64),
      summary: {
        allowed: 3,
        approval_required: 1,
        denied: 0,
        unknown: 2,
      },
    })).toEqual({
      approvalCount: 1,
      blockedCount: 0,
      evidence: "aaaaaaaaaaaa",
      unknownCount: 2,
    });
    expect(permissionSimulationHighlights(undefined)).toBeNull();
  });

  it("finds and consumes only the active at-file token", () => {
    const value = "Review this @src/app";
    const token = activeAtQuery(value, value.length);
    expect(token).toEqual({ query: "src/app", start: 12, end: 20 });
    expect(consumeAtQuery(value, token!)).toBe("Review this ");
    expect(activeAtQuery("email@example.com", 17)).toBeNull();
  });
});
