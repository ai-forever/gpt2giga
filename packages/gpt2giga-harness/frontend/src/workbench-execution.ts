import type { HarnessOption, RunPreflightResponse } from "./api";

export type InvocationMode = "headless" | "native";
export type ExecutionTransport = "native_structured" | "native_terminal" | "one_shot";
export type AuthorityLevel = "read_only" | "workspace_write";
export type TaskIntent = "ask" | "review" | "change";
export type WorkbenchKind = "coding_agent" | "direct_chat";

export interface ProductExecutionSelection {
  authority: AuthorityLevel;
  intent: TaskIntent;
  kind: WorkbenchKind;
}

export interface LegacyProductSelectionResolution {
  selection: ProductExecutionSelection;
  warning: "legacy_mode_alias" | "legacy_mode_unmapped_read_only";
}

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

export function workbenchKindForHarness(
  harness: HarnessOption | undefined,
): WorkbenchKind {
  return harness?.spec.capabilities?.includes("agent_cli")
    ? "coding_agent"
    : "direct_chat";
}

export function harnessesForWorkbenchKind(
  harnesses: readonly HarnessOption[],
  kind: WorkbenchKind,
): HarnessOption[] {
  const requiredCapability =
    kind === "coding_agent" ? "agent_cli" : "chat_completions";
  return harnesses.filter(
    (harness) => harness.spec.capabilities?.includes(requiredCapability),
  );
}

export function normalizeProductSelection(
  harness: HarnessOption | undefined,
  current: ProductExecutionSelection,
): ProductExecutionSelection {
  if (harness === undefined) return current;
  const supportedKind = workbenchKindForHarness(harness);
  return current.kind === supportedKind
    ? current
    : { ...current, kind: supportedKind };
}

export function migrateLegacyProductSelection(
  mode: string | undefined,
  kind: WorkbenchKind,
): ProductExecutionSelection {
  return resolveLegacyProductSelection(mode, kind).selection;
}

export function resolveLegacyProductSelection(
  mode: string | undefined,
  kind: WorkbenchKind,
): LegacyProductSelectionResolution {
  if (mode === "edit") {
    return {
      selection: { authority: "workspace_write", intent: "change", kind },
      warning: "legacy_mode_alias",
    };
  }
  if (mode === "read") {
    return {
      selection: { authority: "read_only", intent: "review", kind },
      warning: "legacy_mode_alias",
    };
  }
  if (mode === "plan" || mode === undefined) {
    return {
      selection: { authority: "read_only", intent: "ask", kind },
      warning: "legacy_mode_alias",
    };
  }
  return {
    selection: { authority: "read_only", intent: "ask", kind },
    warning: "legacy_mode_unmapped_read_only",
  };
}

export function legacyModeForProductSelection(
  selection: ProductExecutionSelection,
): "edit" | "plan" | "read" {
  if (selection.intent === "ask") return "plan";
  if (selection.intent === "review") return "read";
  return selection.authority === "workspace_write" ? "edit" : "read";
}

export function admittedExecutionTransport(
  harness: HarnessOption | undefined,
  kind: WorkbenchKind,
): ExecutionTransport {
  if (kind === "direct_chat") return "one_shot";
  const structured = harness?.workbench_transport?.options.find(
    (option) => option.id === "native_structured",
  );
  return structured?.status === "ready" ? "native_structured" : "one_shot";
}

export function permissionSimulationHighlights(
  simulation: RunPreflightResponse["preflight"]["permission_simulation"],
): {
  approvalCount: number;
  blockedCount: number;
  evidence: string;
  unknownCount: number;
} | null {
  if (simulation === undefined) return null;
  return {
    approvalCount: simulation.summary.approval_required,
    blockedCount: simulation.blocked_actions.length,
    evidence: simulation.simulation_hash.slice(0, 12),
    unknownCount: simulation.summary.unknown,
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
