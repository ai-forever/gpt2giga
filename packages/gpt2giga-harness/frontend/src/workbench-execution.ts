import type { HarnessOption } from "./api";

export type InvocationMode = "headless" | "native";

export interface WorkbenchExecutionSelection {
  capability: string;
  invocationMode: InvocationMode;
}

export function availableInvocationModes(
  harness: HarnessOption | undefined,
): readonly InvocationMode[] {
  if (
    harness?.spec.supports_native_sessions === true &&
    harness.compatibility?.compatible === true
  ) {
    return ["headless", "native"];
  }
  return ["headless"];
}

export function normalizeExecutionSelection(
  harness: HarnessOption | undefined,
  current: WorkbenchExecutionSelection,
): WorkbenchExecutionSelection {
  const modes = availableInvocationModes(harness);
  const capabilities = harness?.spec.capabilities ?? [];
  return {
    invocationMode: modes.includes(current.invocationMode)
      ? current.invocationMode
      : modes[0] ?? "headless",
    capability: capabilities.includes(current.capability)
      ? current.capability
      : capabilities[0] ?? "chat_completions",
  };
}

export function capabilityPresentation(capability: string): {
  label: string;
  detail: string;
} {
  if (capability === "agent_cli") {
    return {
      label: "Coding agent",
      detail: "Works in the selected workspace with governed tool and file access.",
    };
  }
  return {
    label: "Direct chat",
    detail: "Calls the selected model route without a coding-agent workspace loop.",
  };
}

export function activeAtQuery(
  value: string,
  caret: number,
): { query: string; start: number; end: number } | null {
  const prefix = value.slice(0, Math.max(0, caret));
  const match = /(?:^|\s)@([^\s@]*)$/.exec(prefix);
  if (match === null) return null;
  const query = match[1] ?? "";
  return {
    query,
    start: prefix.length - query.length - 1,
    end: prefix.length,
  };
}

export function consumeAtQuery(
  value: string,
  token: { start: number; end: number },
): string {
  const before = value.slice(0, token.start);
  const after = value.slice(token.end);
  return `${before}${before && !before.endsWith(" ") ? " " : ""}${after}`;
}
