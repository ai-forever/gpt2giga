import type { MessageProjection, RunSummary, TokenUsageProjection } from "./api";
import type { RunStreamEvent } from "./stream-store";

const terminalRunStatuses = new Set(["succeeded", "failed", "canceled"]);
const terminalEventTypes = new Set(["run_finished", "run_canceled"]);

export interface WorkbenchStreamProjection {
  assistantText: string;
  generatedFiles: readonly RunStreamEvent[];
  plan: readonly WorkbenchPlanItem[];
  reasoningText: string;
  terminalEvent: RunStreamEvent | null;
  toolActivities: readonly WorkbenchToolActivity[];
  usage: TokenUsageProjection;
}

export interface WorkbenchPlanItem {
  status: "completed" | "in_progress" | "pending";
  step: string;
}

export interface WorkbenchToolActivity {
  id: string;
  label: string;
  name: string;
  result?: unknown;
  status: string;
}

export function projectWorkbenchStream(
  events: readonly RunStreamEvent[],
  messages: readonly MessageProjection[],
  runId: string | undefined,
): WorkbenchStreamProjection {
  if (runId === undefined) {
    return {
      assistantText: "",
      generatedFiles: [],
      plan: [],
      reasoningText: "",
      terminalEvent: null,
      toolActivities: [],
      usage: {},
    };
  }
  const hasRetainedResponse = messages.some(
    (item) =>
      item.run_id === runId && (item.role === "assistant" || item.role === "error"),
  );
  const generatedFiles: RunStreamEvent[] = [];
  const toolActivities = new Map<string, WorkbenchToolActivity>();
  let assistantText = "";
  let plan: readonly WorkbenchPlanItem[] = [];
  const reasoningParts = { model: [] as string[], summary: [] as string[], text: [] as string[] };
  let terminalEvent: RunStreamEvent | null = null;
  const usage: TokenUsageProjection = {};

  for (const event of events) {
    if (event.run_id !== runId) continue;
    if (event.type === "generated_file") generatedFiles.push(event);
    if (event.type.startsWith("tool_call_") || event.type === "plan_updated") {
      const projected = projectToolPayload(event.payload, event.id);
      if (projected.plan.length > 0) {
        plan = projected.plan;
      } else if (projected.activity !== null) {
        toolActivities.set(projected.activity.id, projected.activity);
      }
    }
    if (!hasRetainedResponse && event.type === "message_delta") {
      const delta = event.payload?.delta;
      if (typeof delta === "string") assistantText += delta;
    }
    if (!hasRetainedResponse && event.type === "reasoning_delta") {
      const delta = event.payload?.delta;
      const kind = typeof event.payload?.kind === "string" ? event.payload.kind : "model";
      if (typeof delta === "string") {
        if (kind === "summary") reasoningParts.summary.push(delta);
        else if (kind === "text") reasoningParts.text.push(delta);
        else reasoningParts.model.push(delta);
      }
    }
    if (event.type === "usage") mergeUsage(usage, event.payload);
    if (terminalEventTypes.has(event.type)) terminalEvent = event;
  }

  return {
    assistantText,
    generatedFiles,
    plan,
    reasoningText: (
      reasoningParts.summary.length > 0
        ? reasoningParts.summary
        : reasoningParts.model.length > 0
          ? reasoningParts.model
          : reasoningParts.text
    ).join(""),
    terminalEvent,
    toolActivities: [...toolActivities.values()],
    usage,
  };
}

export function projectToolPayload(
  payload: Readonly<Record<string, unknown>> | undefined,
  fallbackId: string,
): { activity: WorkbenchToolActivity | null; plan: readonly WorkbenchPlanItem[] } {
  if (payload === undefined) return { activity: null, plan: [] };
  const name = typeof payload.name === "string" ? payload.name : "tool";
  const plan = name === "update_plan" ? parsePlan(payload.arguments) : [];
  if (plan.length > 0) return { activity: null, plan };
  const id = typeof payload.tool_call_id === "string" ? payload.tool_call_id : fallbackId;
  const status = typeof payload.status === "string" ? payload.status : "running";
  return {
    activity: {
      id,
      label: toolLabel(name, payload.arguments),
      name,
      ...(payload.result === undefined ? {} : { result: payload.result }),
      status,
    },
    plan: [],
  };
}

function mergeUsage(
  target: TokenUsageProjection,
  payload: Readonly<Record<string, unknown>> | undefined,
): void {
  if (payload === undefined) return;
  const keys = [
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "cached_input_tokens",
    "reasoning_output_tokens",
    "tool_tokens",
  ] as const;
  for (const key of keys) {
    const value = payload[key];
    if (typeof value === "number" && Number.isFinite(value) && value >= 0) {
      target[key] = value;
    }
  }
}

function parsePlan(value: unknown): readonly WorkbenchPlanItem[] {
  if (!isRecord(value) || !Array.isArray(value.plan)) return [];
  return value.plan.flatMap((item) => {
    if (!isRecord(item) || typeof item.step !== "string") return [];
    const status = item.status;
    if (status !== "completed" && status !== "in_progress" && status !== "pending") {
      return [];
    }
    return [{ status, step: item.step }];
  });
}

function toolLabel(name: string, value: unknown): string {
  const argumentsValue = isRecord(value) ? value : {};
  const path = firstText(argumentsValue.path, argumentsValue.file, argumentsValue.filename);
  if (name.includes("read") && path !== null) return `Reading ${path}`;
  if (name === "web_search") {
    const query = firstText(argumentsValue.query);
    return query === null ? "Searching the web" : `Searching for ${query}`;
  }
  if (name === "shell") {
    const command = firstText(argumentsValue.command);
    return command === null ? "Running command" : `Running ${firstLine(command)}`;
  }
  if (name.includes("file") || name.includes("edit") || name.includes("patch")) {
    return path === null ? "Editing files" : `Editing ${path}`;
  }
  return name.replaceAll("_", " ");
}

function firstText(...values: unknown[]): string | null {
  const value = values.find((item) => typeof item === "string" && item.trim());
  return typeof value === "string" ? value.trim() : null;
}

function firstLine(value: string): string {
  const line = value.split("\n", 1)[0] ?? value;
  return line.length > 72 ? `${line.slice(0, 69)}...` : line;
}

function isRecord(value: unknown): value is Readonly<Record<string, unknown>> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function workbenchRunActive(
  run: RunSummary | null,
  selectedRunId: string | undefined,
  locallyStartedRunId: string | undefined,
  terminalEvent: RunStreamEvent | null,
): boolean {
  if (selectedRunId === undefined || terminalEvent?.run_id === selectedRunId) return false;
  if (locallyStartedRunId === selectedRunId) return true;
  return (
    run?.id === selectedRunId &&
    !terminalRunStatuses.has(run.status)
  );
}
