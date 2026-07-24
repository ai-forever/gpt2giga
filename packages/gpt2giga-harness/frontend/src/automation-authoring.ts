import type { AutomationSection } from "./automation-actions";

export type AutomationAuthoringMode = "create" | "edit" | "duplicate" | "delete";

export interface AutomationAuthoringRequest {
  mode: AutomationAuthoringMode;
  section: AutomationSection;
  id?: string;
}

export interface DeletePreview {
  kind: string;
  id: string;
  source_hash: string;
  dependents: Array<{ kind: string; id: string; status: string }>;
  active_dependents: Array<{ kind: string; id: string; status: string }>;
  confirmation_required: true;
}

export interface AutomationStarter {
  id: string;
  title: string;
  description: string;
  sequence: number;
}

export type ScheduleCadencePreset =
  | "daily"
  | "once"
  | "weekdays"
  | "weekly"
  | "custom";

export interface ScheduleFormDefinition {
  base: Record<string, unknown>;
  title: string;
  targetKind: "agent" | "eval" | "workflow";
  targetId: string;
  cadencePreset: ScheduleCadencePreset;
  timezone: string;
  startAt: string;
  weekday: string;
  customRrule: string;
  prompt: string;
  desktopNotifications: boolean;
}

export function automationStarter(section: AutomationSection): AutomationStarter {
  if (section === "agents") {
    return {
      id: "code-reviewer",
      title: "Code Reviewer",
      description: "A read-only Codex agent that returns concrete review findings.",
      sequence: 1,
    };
  }
  if (section === "workflows") {
    return {
      id: "review-change",
      title: "Review Change",
      description: "Runs the Code Reviewer agent with a reusable prompt.",
      sequence: 2,
    };
  }
  return {
    id: "weekday-review",
    title: "Weekday Review",
    description: "Runs the Review Change workflow every weekday in an isolated worktree.",
    sequence: 3,
  };
}

export function defaultDefinition(section: AutomationSection): {
  id: string;
  content: string;
} {
  if (section === "agents") {
    return {
      id: "code-reviewer",
      content: [
        "id: code-reviewer",
        "title: Code Reviewer",
        "description: Reviews a change and returns concrete findings without editing files.",
        "schema_version: 1",
        "harness_id: codex-cli",
        "instructions: >-",
        "  Inspect the requested change, cite exact files, and prioritize correctness,",
        "  compatibility, and missing tests. Do not edit files.",
        "api_mode: v2",
        "invocation_mode: headless",
        "mode: read",
        "workspace_policy: current",
        "permission_profile: unattended",
        "budgets:",
        "  timeout_seconds: 300",
        "  max_attempts: 1",
        "",
      ].join("\n"),
    };
  }
  if (section === "workflows") {
    return {
      id: "review-change",
      content: [
        "id: review-change",
        "title: Review Change",
        "description: Run the reusable Code Reviewer agent.",
        "schema_version: 1",
        "version: '1.0.0'",
        "inputs:",
        "  prompt: Review the current change.",
        "steps:",
        "  - id: review",
        "    kind: agent",
        "    agent_id: code-reviewer",
        "    prompt: '${prompt}'",
        "",
      ].join("\n"),
    };
  }
  const starter = scheduleContentFromForm(
    "weekday-review",
    {
      base: {},
      title: "Weekday Review",
      targetKind: "workflow",
      targetId: "review-change",
      cadencePreset: "weekdays",
      timezone: resolvedTimezone(),
      startAt: nextMorning(),
      weekday: "MO",
      customRrule: "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR",
      prompt: "Review the current change and report actionable findings.",
      desktopNotifications: true,
    },
  );
  return {
    id: "weekday-review",
    content: starter,
  };
}

export function scheduleFormFromContent(content: string): ScheduleFormDefinition {
  const payload = parseScheduleContent(content);
  const target = record(payload.target);
  const cadence = record(payload.cadence);
  const notifications = record(payload.notifications);
  const cadenceKind = text(cadence.kind);
  const rrule = text(cadence.rrule);
  const interval = Number(cadence.interval_seconds);
  const cadencePreset: ScheduleCadencePreset =
    cadenceKind === "once"
      ? "once"
      : cadenceKind === "interval" && interval === 86400
        ? "daily"
        : rrule === "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"
          ? "weekdays"
          : /^FREQ=WEEKLY;BYDAY=[A-Z]{2}$/.test(rrule)
            ? "weekly"
            : "custom";
  return {
    base: payload,
    title: text(payload.title) || text(payload.id),
    targetKind: ["agent", "eval", "workflow"].includes(text(target.kind))
      ? (text(target.kind) as ScheduleFormDefinition["targetKind"])
      : "workflow",
    targetId: text(target.id),
    cadencePreset,
    timezone: text(cadence.timezone) || resolvedTimezone(),
    startAt: text(cadence.start_at).slice(0, 16) || nextMorning(),
    weekday: rrule.match(/BYDAY=([A-Z]{2})$/)?.[1] ?? "MO",
    customRrule: rrule || "FREQ=DAILY",
    prompt: text(payload.prompt),
    desktopNotifications: notifications.desktop === true,
  };
}

export function scheduleContentFromForm(
  id: string,
  form: ScheduleFormDefinition,
): string {
  const cadence: Record<string, unknown> = {
    kind: form.cadencePreset === "once"
      ? "once"
      : form.cadencePreset === "daily"
        ? "interval"
        : "rrule",
    timezone: form.timezone,
    start_at: form.startAt.length === 16 ? `${form.startAt}:00` : form.startAt,
  };
  if (form.cadencePreset === "daily") cadence.interval_seconds = 86400;
  if (form.cadencePreset === "weekdays") {
    cadence.rrule = "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR";
  }
  if (form.cadencePreset === "weekly") {
    cadence.rrule = `FREQ=WEEKLY;BYDAY=${form.weekday}`;
  }
  if (form.cadencePreset === "custom") cadence.rrule = form.customRrule;
  const payload: Record<string, unknown> = {
    ...form.base,
    id,
    title: form.title,
    target: { kind: form.targetKind, id: form.targetId },
    cadence,
    prompt: form.prompt,
    workspace_policy: "worktree",
    notifications: { ...record(form.base.notifications), desktop: form.desktopNotifications },
  };
  delete payload.source_hash;
  delete payload.target_hash;
  delete payload.target_snapshot;
  return JSON.stringify(payload, null, 2);
}

export function sourceFromDetail(
  section: AutomationSection,
  response: unknown,
): { id: string; content: string; sourceHash: string | null } {
  const root = record(response);
  if (section === "agents") {
    const profile = record(root.profile);
    return {
      id: text(profile.id),
      content: text(root.source),
      sourceHash: nullableText(profile.source_hash),
    };
  }
  if (section === "workflows") {
    const workflow = record(root.workflow);
    return {
      id: text(workflow.id),
      content: text(root.source),
      sourceHash: nullableText(workflow.source_hash),
    };
  }
  const definition = record(root.definition);
  const editable = { ...definition };
  delete editable.source_hash;
  delete editable.target_hash;
  delete editable.target_snapshot;
  return {
    id: text(definition.id),
    content: JSON.stringify(editable, null, 2),
    sourceHash: nullableText(definition.source_hash),
  };
}

export function duplicateDefinition(
  section: AutomationSection,
  source: { id: string; content: string; sourceHash: string | null },
): { id: string; content: string; sourceHash: null } {
  const id = `${source.id}-copy`;
  if (section === "schedules") {
    const payload = JSON.parse(source.content) as Record<string, unknown>;
    payload.id = id;
    payload.title = `${String(payload.title || source.id)} Copy`;
    delete payload.source_hash;
    delete payload.target_hash;
    delete payload.target_snapshot;
    return { id, content: JSON.stringify(payload, null, 2), sourceHash: null };
  }
  const lines = source.content.split("\n");
  const content = lines
    .map((line) => {
      if (/^id:\s*/.test(line)) return `id: ${id}`;
      if (/^title:\s*/.test(line)) return `${line} Copy`;
      return line;
    })
    .join("\n");
  return { id, content, sourceHash: null };
}

export function parseScheduleContent(content: string): Record<string, unknown> {
  const value = JSON.parse(content) as unknown;
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("Schedule definition must be a JSON object.");
  }
  return value as Record<string, unknown>;
}

function record(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function nullableText(value: unknown): string | null {
  return typeof value === "string" && value ? value : null;
}

function resolvedTimezone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
}

function nextMorning(): string {
  const date = new Date();
  date.setDate(date.getDate() + 1);
  date.setHours(9, 0, 0, 0);
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}
