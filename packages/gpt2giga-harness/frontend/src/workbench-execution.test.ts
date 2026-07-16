import { describe, expect, it } from "vitest";

import type { HarnessOption } from "./api";
import {
  activeAtQuery,
  availableInvocationModes,
  capabilityPresentation,
  consumeAtQuery,
  normalizeExecutionSelection,
} from "./workbench-execution";

function harness(overrides: Partial<HarnessOption> = {}): HarnessOption {
  return {
    spec: {
      id: "codex-cli",
      capabilities: ["agent_cli"],
      supports_native_sessions: true,
    },
    compatibility: { compatible: true },
    ...overrides,
  };
}

describe("Workbench execution semantics", () => {
  it("offers native only for capability-proven CLIs", () => {
    expect(availableInvocationModes(harness())).toEqual(["headless", "native"]);
    expect(availableInvocationModes(harness({ compatibility: { compatible: false } }))).toEqual(["headless"]);
    expect(availableInvocationModes(harness({ spec: { id: "direct-chat", capabilities: ["chat_completions"] } }))).toEqual(["headless"]);
  });

  it("normalizes stale invocation and capability after a harness change", () => {
    expect(normalizeExecutionSelection(
      harness({ spec: { id: "direct-chat", capabilities: ["chat_completions"] } }),
      { capability: "agent_cli", invocationMode: "native" },
    )).toEqual({ capability: "chat_completions", invocationMode: "headless" });
  });

  it("presents capabilities as operator concepts", () => {
    expect(capabilityPresentation("agent_cli").label).toBe("Coding agent");
    expect(capabilityPresentation("chat_completions").label).toBe("Direct chat");
  });

  it("finds and consumes only the active at-file token", () => {
    const value = "Review this @src/app";
    const token = activeAtQuery(value, value.length);
    expect(token).toEqual({ query: "src/app", start: 12, end: 20 });
    expect(consumeAtQuery(value, token!)).toBe("Review this ");
    expect(activeAtQuery("email@example.com", 17)).toBeNull();
  });
});
