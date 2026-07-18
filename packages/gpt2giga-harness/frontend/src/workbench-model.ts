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
  children?: readonly WorkbenchToolActivity[];
  detail?: string;
  id: string;
  label: string;
  name: string;
  parentId?: string;
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
        const previous = toolActivities.get(projected.activity.id);
        toolActivities.set(
          projected.activity.id,
          previous === undefined
            ? projected.activity
            : mergeToolActivity(previous, projected.activity),
        );
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
    toolActivities: nestWorkbenchToolActivities([...toolActivities.values()]),
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
  const parentId =
    typeof payload.parent_tool_call_id === "string"
      ? payload.parent_tool_call_id
      : undefined;
  const detail = toolDetail(name, payload.arguments);
  return {
    activity: {
      id,
      label: toolLabel(name, payload.arguments),
      name,
      ...(detail === null ? {} : { detail }),
      ...(parentId === undefined ? {} : { parentId }),
      ...(payload.result === undefined ? {} : { result: payload.result }),
      status,
    },
    plan: [],
  };
}

export function nestWorkbenchToolActivities(
  activities: readonly WorkbenchToolActivity[],
): readonly WorkbenchToolActivity[] {
  const byId = new Map<string, WorkbenchToolActivity>(
    activities.map((activity) => [activity.id, { ...activity, children: undefined }]),
  );
  const childIds = new Set<string>();

  for (const activity of activities) {
    if (
      activity.parentId === undefined ||
      activity.parentId === activity.id ||
      !byId.has(activity.parentId) ||
      toolParentChainContains(activity.parentId, activity.id, byId)
    ) {
      continue;
    }
    const parent = byId.get(activity.parentId);
    const child = byId.get(activity.id);
    if (parent === undefined || child === undefined) continue;
    parent.children = [...(parent.children ?? []), child];
    childIds.add(activity.id);
  }

  return activities.flatMap((activity) => {
    const nested = byId.get(activity.id);
    return nested === undefined || childIds.has(activity.id) ? [] : [nested];
  });
}

function mergeToolActivity(
  previous: WorkbenchToolActivity,
  current: WorkbenchToolActivity,
): WorkbenchToolActivity {
  return {
    ...previous,
    ...current,
    ...(current.parentId === undefined && previous.parentId !== undefined
      ? { parentId: previous.parentId }
      : {}),
    ...(current.result === undefined && previous.result !== undefined
      ? { result: previous.result }
      : {}),
  };
}

function toolParentChainContains(
  parentId: string,
  childId: string,
  byId: ReadonlyMap<string, WorkbenchToolActivity>,
): boolean {
  const visited = new Set<string>();
  let currentId: string | undefined = parentId;
  while (currentId !== undefined && !visited.has(currentId)) {
    if (currentId === childId) return true;
    visited.add(currentId);
    currentId = byId.get(currentId)?.parentId;
  }
  return false;
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
  if (name === "spawn_agent") {
    const agent = firstSubagent(argumentsValue.subagents);
    const agentName = firstText(agent?.name, agent?.nickname, agent?.id);
    return agentName === null ? "Subagent" : `Subagent ${agentName}`;
  }
  if (name === "send_input") return "Message to subagent";
  if (name === "wait" || name === "wait_agent") return "Waiting for subagent";
  const path = firstText(
    argumentsValue.path,
    argumentsValue.file,
    argumentsValue.file_path,
    argumentsValue.filename,
  );
  if (name === "read_file") {
    return path === null ? "Reading files" : `Reading ${path}`;
  }
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

function toolDetail(name: string, value: unknown): string | null {
  if (name !== "spawn_agent") return null;
  const argumentsValue = isRecord(value) ? value : {};
  const agent = firstSubagent(argumentsValue.subagents);
  const role = firstText(agent?.role, agent?.type);
  const prompt = firstText(argumentsValue.prompt, agent?.prompt, agent?.description);
  const parts = [role, prompt === null ? null : firstLine(prompt)].filter(
    (item): item is string => item !== null,
  );
  return parts.length === 0 ? null : parts.join(" · ");
}

function firstSubagent(value: unknown): Readonly<Record<string, unknown>> | null {
  if (!Array.isArray(value)) return null;
  return value.find(isRecord) ?? null;
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
