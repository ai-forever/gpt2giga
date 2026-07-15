export interface AgentProjection {
  id: string;
  title: string;
  harnessId: string;
  mode: string;
  model: string | null;
}

export interface WorkflowProjection {
  id: string;
  title: string;
  trigger: string;
  stepCount: number;
  lastRunStatus: string | null;
  lastRunAt: string | null;
}

export interface ScheduleProjection {
  id: string;
  title: string;
  target: string;
  status: string;
  nextRunAt: string | null;
  workerOnline: boolean;
}

export interface AutomationProjection {
  agents: AgentProjection[];
  workflows: WorkflowProjection[];
  schedules: ScheduleProjection[];
  contentFree: true;
}

export interface ArenaProjection {
  id: string;
  status: string;
  harnessCount: number;
  createdAt: string;
  updatedAt: string;
}

export interface EvalProjection {
  name: string;
  description: string;
  caseCount: number;
  latestRunId: string | null;
  latestStatus: string | null;
  latestScore: number | null;
  baselineRunId: string | null;
}

export interface BaselineProjection {
  specName: string;
  evalRunId: string;
  pinnedAt: string | null;
}

export interface EvaluationProjection {
  arenas: ArenaProjection[];
  evals: EvalProjection[];
  baselines: BaselineProjection[];
  contentFree: true;
}

export interface HarnessProjection {
  id: string;
  title: string;
  kind: string;
  status: string;
  reason: string;
}

export interface RouteProjection {
  apiMode: string;
  model: string;
}

export interface McpProjection {
  id: string;
  title: string;
  transport: string;
  enabled: boolean;
  trusted: boolean;
  status: string;
}

export interface IntegrationsProjection {
  harnesses: HarnessProjection[];
  routes: RouteProjection[];
  mcp: McpProjection[];
  contentFree: true;
}

export interface DoctorFindingProjection {
  id: string;
  status: string;
  summary: string;
  remedy: string | null;
  command: string | null;
}

export interface DoctorProjection {
  harnessId: string;
  status: "ready" | "degraded" | "blocked";
  findings: DoctorFindingProjection[];
  contentFree: true;
}

type UnknownRecord = Record<string, unknown>;

const MAX_ROWS = 100;

export function projectAutomation(
  agentsResponse: unknown,
  workflowsResponse: unknown,
  schedulesResponse: unknown,
): AutomationProjection {
  const workflowRuns = array(record(workflowsResponse).runs);
  const latestRunByWorkflow = new Map<string, UnknownRecord>();
  for (const value of workflowRuns) {
    const run = record(value);
    const workflowId = text(run.workflow_id);
    if (workflowId && !latestRunByWorkflow.has(workflowId)) {
      latestRunByWorkflow.set(workflowId, run);
    }
  }

  return {
    agents: array(record(agentsResponse).agents)
      .slice(0, MAX_ROWS)
      .map((value) => {
        const item = record(value);
        return {
          id: text(item.id),
          title: text(item.title) || text(item.id),
          harnessId: text(item.harness_id),
          mode: text(item.mode) || "plan",
          model: nullableText(item.model),
        };
      })
      .filter((item) => item.id),
    workflows: array(record(workflowsResponse).workflows)
      .slice(0, MAX_ROWS)
      .map((value) => {
        const item = record(value);
        const latest = latestRunByWorkflow.get(text(item.id));
        const triggers = array(item.triggers).map((trigger) => text(trigger)).filter(Boolean);
        return {
          id: text(item.id),
          title: text(item.title) || text(item.id),
          trigger: triggers.join(", ") || "manual",
          stepCount: array(item.steps).length,
          lastRunStatus: latest === undefined ? null : nullableText(latest.status),
          lastRunAt: latest === undefined ? null : nullableText(latest.updated_at),
        };
      })
      .filter((item) => item.id),
    schedules: array(record(schedulesResponse).schedules)
      .slice(0, MAX_ROWS)
      .map((value) => {
        const item = record(value);
        const definition = record(item.definition);
        const target = record(definition.target);
        const state = record(item.state);
        const worker = record(item.worker);
        const preview = array(item.preview);
        return {
          id: text(definition.id),
          title: text(definition.title) || text(definition.id),
          target: [text(target.kind), text(target.id)].filter(Boolean).join(":"),
          status: text(state.status) || "disabled",
          nextRunAt: nullableText(state.next_run_at) ?? nullableText(preview[0]),
          workerOnline: worker.online === true,
        };
      })
      .filter((item) => item.id),
    contentFree: true,
  };
}

export function projectEvaluation(
  evaluateResponse: unknown,
  arenaResponse: unknown,
): EvaluationProjection {
  const evaluate = record(evaluateResponse);
  const runs = array(evaluate.runs).map(record);
  const latestRunBySpec = new Map<string, UnknownRecord>();
  for (const run of runs) {
    const specName = text(run.spec_name);
    if (specName && !latestRunBySpec.has(specName)) latestRunBySpec.set(specName, run);
  }
  const evals = array(evaluate.quality_specs)
    .slice(0, MAX_ROWS)
    .map((value) => {
      const item = record(value);
      const name = text(item.name);
      const latest = latestRunBySpec.get(name);
      const baseline = record(item.baseline);
      const summary = latest === undefined ? {} : record(latest.summary);
      return {
        name,
        description: text(item.description),
        caseCount: number(item.case_count),
        latestRunId: latest === undefined ? null : nullableText(latest.id),
        latestStatus: latest === undefined ? null : nullableText(latest.status),
        latestScore: latest === undefined ? null : nullableNumber(summary.score),
        baselineRunId: nullableText(baseline.eval_run_id),
      };
    })
    .filter((item) => item.name);

  return {
    arenas: array(record(arenaResponse).arenas)
      .slice(0, MAX_ROWS)
      .map((value) => {
        const item = record(value);
        return {
          id: text(item.id),
          status: text(item.status) || "unknown",
          harnessCount: array(item.harness_ids).length,
          createdAt: text(item.created_at),
          updatedAt: text(item.updated_at),
        };
      })
      .filter((item) => item.id),
    evals,
    baselines: array(evaluate.quality_specs)
      .slice(0, MAX_ROWS)
      .flatMap((value) => {
        const item = record(value);
        const baseline = record(item.baseline);
        const evalRunId = text(baseline.eval_run_id);
        return evalRunId
          ? [{ specName: text(item.name), evalRunId, pinnedAt: nullableText(baseline.pinned_at) }]
          : [];
      }),
    contentFree: true,
  };
}

export function projectIntegrations(
  harnessesResponse: unknown,
  defaultsResponse: unknown,
  mcpResponse: unknown,
): IntegrationsProjection {
  const defaults = record(defaultsResponse);
  return {
    harnesses: array(record(harnessesResponse).harnesses)
      .slice(0, MAX_ROWS)
      .map((value) => {
        const item = record(value);
        const spec = record(item.spec);
        const availability = record(item.availability);
        return {
          id: text(spec.id),
          title: text(spec.title) || text(spec.id),
          kind: text(spec.kind),
          status: text(availability.status) || "unknown",
          reason: text(availability.reason) || text(availability.detail),
        };
      })
      .filter((item) => item.id),
    routes: [
      {
        apiMode: text(defaults.default_api_mode) || "v2",
        model: text(defaults.default_model) || "GigaChat",
      },
    ],
    mcp: array(record(mcpResponse).servers)
      .slice(0, MAX_ROWS)
      .map((value) => {
        const item = record(value);
        const descriptor = record(item.descriptor);
        const probe = record(item.latest_probe);
        return {
          id: text(descriptor.id),
          title: text(descriptor.title) || text(descriptor.id),
          transport: text(descriptor.transport),
          enabled: descriptor.enabled === true,
          trusted: descriptor.trusted === true,
          status: text(probe.status) || (descriptor.enabled === true ? "not probed" : "disabled"),
        };
      })
      .filter((item) => item.id),
    contentFree: true,
  };
}

export function projectDoctor(response: unknown): DoctorProjection {
  const readiness = record(record(response).preflight).readiness;
  const report = record(readiness);
  const plan = record(report.plan);
  const summary = record(report.summary);
  const status: DoctorProjection["status"] =
    report.blocked === true || number(summary.blocked) > 0
      ? "blocked"
      : number(summary.degraded) > 0
        ? "degraded"
        : "ready";
  return {
    harnessId: text(plan.harness_id),
    status,
    findings: array(report.findings)
      .slice(0, MAX_ROWS)
      .map((value) => {
        const item = record(value);
        const remediation = record(array(item.remediation)[0]);
        return {
          id: text(item.id),
          status: text(item.status),
          summary: text(item.summary) || text(item.message) || text(item.detail),
          remedy: nullableText(remediation.message),
          command: nullableText(remediation.command),
        };
      })
      .filter((item) => item.id),
    contentFree: true,
  };
}

function record(value: unknown): UnknownRecord {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as UnknownRecord)
    : {};
}

function array(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function nullableText(value: unknown): string | null {
  const valueText = text(value);
  return valueText || null;
}

function number(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function nullableNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}
