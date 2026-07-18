import type { HarnessOption } from "./api";

export type InvocationMode = "headless" | "native";
export type ExecutionTransport = "native_structured" | "native_terminal" | "one_shot";

export interface WorkbenchExecutionSelection {
  capability: string;
  executionTransport: ExecutionTransport;
}

export function availableExecutionTransports(
  harness: HarnessOption | undefined,
): readonly ExecutionTransport[] {
  const projected = harness?.workbench_transport?.options.map((option) => option.id);
  if (projected?.length) return projected;
  return harness?.spec.supports_native_sessions === true
    ? ["one_shot", "native_terminal"]
    : ["one_shot"];
}

export function normalizeExecutionSelection(
  harness: HarnessOption | undefined,
  current: WorkbenchExecutionSelection,
): WorkbenchExecutionSelection {
  const transports = availableExecutionTransports(harness);
  const capabilities = harness?.spec.capabilities ?? [];
  const preferred = harness?.workbench_transport?.default ?? transports[0] ?? "one_shot";
  return {
    executionTransport: transports.includes(current.executionTransport)
      ? current.executionTransport
      : preferred,
    capability: capabilities.includes(current.capability)
      ? current.capability
      : capabilities[0] ?? "chat_completions",
  };
}

export function invocationModeForTransport(
  transport: ExecutionTransport,
): InvocationMode {
  return transport === "native_terminal" ? "native" : "headless";
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
