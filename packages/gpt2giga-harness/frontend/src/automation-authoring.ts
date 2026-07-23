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

export function defaultDefinition(section: AutomationSection): {
  id: string;
  content: string;
} {
  if (section === "agents") {
    return {
      id: "new-agent",
      content: [
        "id: new-agent",
        "title: New Agent",
        "description: A reusable project agent.",
        "harness_id: codex-cli",
        "mode: plan",
        "budgets:",
        "  max_attempts: 1",
        "",
      ].join("\n"),
    };
  }
  if (section === "workflows") {
    return {
      id: "new-workflow",
      content: [
        "id: new-workflow",
        "title: New Workflow",
        "version: '1.0.0'",
        "steps:",
        "  - id: plan",
        "    kind: agent",
        "    agent_id: planner",
        "    prompt: 'Plan: ${prompt}'",
        "",
      ].join("\n"),
    };
  }
  return {
    id: "new-schedule",
    content: JSON.stringify(
      {
        id: "new-schedule",
        title: "New Schedule",
        target: { kind: "workflow", id: "review-team" },
        cadence: {
          kind: "interval",
          timezone: "UTC",
          start_at: "2026-07-24T00:00:00",
          interval_seconds: 86400,
        },
        prompt: "Run the scheduled workflow.",
        workspace_policy: "worktree",
      },
      null,
      2,
    ),
  };
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
