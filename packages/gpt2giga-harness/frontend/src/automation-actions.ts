import type { MessageKey } from "./messages";
import type {
  AgentProjection,
  ScheduleProjection,
  WorkflowProjection,
} from "./surface-projections";

export type AutomationSection = "agents" | "workflows" | "schedules";
export type AutomationItem =
  | AgentProjection
  | WorkflowProjection
  | ScheduleProjection;

export interface AutomationActionPlan {
  kind: "agent_run" | "workflow_run" | "schedule_test" | "schedule_run";
  labelKey: MessageKey;
  prompt: "none" | "optional" | "required";
  disabledReason: string | null;
}

export interface AutomationActionResult {
  approvalId: string | null;
  occurrenceId: string | null;
  runId: string | null;
  sessionId: string | null;
  workflowRunId: string | null;
}

export function planAutomationAction(
  section: AutomationSection,
  item: AutomationItem,
): AutomationActionPlan {
  if (section === "agents") {
    const agent = item as AgentProjection;
    return {
      kind: "agent_run",
      labelKey: "runAgent",
      prompt: "required",
      disabledReason: agent.queueable ? null : agent.unavailableReason,
    };
  }
  if (section === "workflows") {
    const workflow = item as WorkflowProjection;
    return {
      kind: "workflow_run",
      labelKey: "runWorkflow",
      prompt: "optional",
      disabledReason: workflow.workerOnline ? null : "worker_offline",
    };
  }
  const schedule = item as ScheduleProjection;
  return schedule.tested
    ? {
        kind: "schedule_run",
        labelKey: "runScheduleNow",
        prompt: "none",
        disabledReason: null,
      }
    : {
        kind: "schedule_test",
        labelKey: "testScheduleNow",
        prompt: "none",
        disabledReason: null,
      };
}

export function createAutomationSubmissionKey(
  section: AutomationSection,
  itemId: string,
): string {
  return `cockpit:${section}:${itemId}:${globalThis.crypto.randomUUID()}`;
}

export function projectAutomationActionResult(
  response: unknown,
): AutomationActionResult {
  const root = record(response);
  const run = record(root.run);
  const result = record(root.result);
  const resultRun = record(result.run);
  const occurrence = record(root.occurrence);
  const approval = record(root.approval);
  const session = record(root.session);

  const workflowRunId = first(
    workflowId(run.id),
    workflowId(result.id),
    workflowId(occurrence.run_id),
  );
  const runId = first(
    retainedRunId(run.id),
    childRunId(run.steps),
    retainedRunId(resultRun.id),
    childRunId(result.steps),
    retainedRunId(occurrence.run_id),
  );
  const sessionId = first(
    text(session.id),
    text(run.session_id),
    text(result.session_id),
    text(resultRun.session_id),
    text(occurrence.destination_session_id),
  );

  return {
    approvalId: text(approval.id),
    occurrenceId: text(occurrence.id),
    runId,
    sessionId,
    workflowRunId,
  };
}

function childRunId(value: unknown): string | null {
  for (const step of array(value)) {
    const runId = retainedRunId(record(record(step).outputs).run_id);
    if (runId !== null) return runId;
  }
  return null;
}

function retainedRunId(value: unknown): string | null {
  const candidate = text(value);
  return candidate?.startsWith("run_") ? candidate : null;
}

function workflowId(value: unknown): string | null {
  const candidate = text(value);
  return candidate?.startsWith("workflow_") ? candidate : null;
}

function first(...values: Array<string | null>): string | null {
  return values.find((value) => value !== null) ?? null;
}

function record(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function array(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function text(value: unknown): string | null {
  return typeof value === "string" && value ? value : null;
}
