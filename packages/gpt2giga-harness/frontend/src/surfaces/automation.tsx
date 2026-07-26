import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from "@tanstack/react-query";
import { Link, useRouterState, useSearch } from "@tanstack/react-router";
import { useMemo, useRef, useState } from "react";

import { mutateCockpit } from "../api";
import {
  automationStarter,
  type AutomationAuthoringRequest,
} from "../automation-authoring";
import {
  createAutomationSubmissionKey,
  planAutomationAction,
  projectAutomationActionResult,
  type AutomationSection,
} from "../automation-actions";
import {
  LoadingRows,
  OperationalRowLink,
  OperationalSurface,
  StatusBadge,
  type OperationalTab,
} from "../components/OperationalSurface";
import { AutomationAuthoringDrawer } from "../components/AutomationAuthoringDrawer";
import { message } from "../messages";
import { usePreferences } from "../preferences-context";
import { requestKeys } from "../request-graph";
import {
  automationSurfaceOptions,
  remainingRequestKeys,
} from "../remaining-request-graph";
import type {
  AgentProjection,
  AutomationProjection,
  ScheduleProjection,
  WorkflowProjection,
} from "../surface-projections";

const tabs: readonly OperationalTab[] = [
  { id: "agents", labelKey: "agents", href: "/cockpit-v2/automation/agents" },
  { id: "workflows", labelKey: "workflows", href: "/cockpit-v2/automation/workflows" },
  { id: "schedules", labelKey: "schedules", href: "/cockpit-v2/automation/schedules" },
];

export function AutomationSurface() {
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const section = pathname.endsWith("/agents")
    ? "agents"
    : pathname.endsWith("/schedules")
      ? "schedules"
      : "workflows";
  const { selected: selectedId } = useSearch({ strict: false });
  const query = useQuery(automationSurfaceOptions());
  const [authoring, setAuthoring] = useState<AutomationAuthoringRequest | null>(null);

  return (
    <>
      <OperationalSurface
        activeTab={section}
        aside={
          <AutomationDetail
            onAuthoring={setAuthoring}
            section={section}
            selectedId={selectedId}
          />
        }
        detailKey="automationDetailMigrated"
        eyebrowKey="automationEyebrow"
        tabs={tabs}
        titleKey="automation"
      >
        <AutomationList
          onCreate={() => setAuthoring({ mode: "create", section })}
          section={section}
          query={query}
          selectedId={selectedId}
        />
      </OperationalSurface>
      {authoring ? (
        <AutomationAuthoringDrawer
          onClose={() => setAuthoring(null)}
          request={authoring}
        />
      ) : null}
    </>
  );
}

function AutomationList({ onCreate, section, query, selectedId }: {
  onCreate: () => void;
  section: AutomationSection;
  query: UseQueryResult<AutomationProjection, Error>;
  selectedId: string | undefined;
}) {
  const { preferences } = usePreferences();
  const locale = preferences.locale;
  if (query.isPending) return <LoadingRows />;
  if (query.isError || query.data === undefined) {
    return (
      <div className="error-state" role="alert">
        <strong>{message(locale, "boundedDataUnavailable")}</strong>
        <span>{query.error?.message}</span>
        <button onClick={() => void query.refetch()} type="button">
          {message(locale, "retry")}
        </button>
      </div>
    );
  }
  const rows = query.data[section];
  return (
    <>
      <div className="operations-toolbar">
        <div>
          <span className="section-kicker">{message(locale, section)}</span>
          <strong>{rows.length} {message(locale, "retainedItems")}</strong>
          <span className="worker-readiness" data-status={query.data.workerOnline ? "ready" : "offline"}>
            {message(locale, query.data.workerOnline ? "workerReady" : "workerOffline")}
          </span>
        </div>
        <div className="automation-authoring-entry">
          <button className="primary-button" onClick={onCreate} type="button">
            + {message(locale, "authoringCreate")}
          </button>
          <span>{message(locale, "authoringValidationHint")}</span>
        </div>
      </div>
      {rows.length === 0 ? (
        <AutomationStarterCard
          locale={locale}
          onCreate={onCreate}
          section={section}
        />
      ) : (
        <div className="operations-table" role="table">
          {rows.map((item) => (
            <AutomationRow key={item.id} item={item} section={section} selected={selectedId === item.id} />
          ))}
        </div>
      )}
    </>
  );
}

function AutomationStarterCard({
  locale,
  onCreate,
  section,
}: {
  locale: "en" | "ru";
  onCreate: () => void;
  section: AutomationSection;
}) {
  const starter = automationStarter(section);
  const command = section === "agents"
    ? "giga run --agent code-reviewer --workspace . \"Review this change\""
    : section === "workflows"
      ? "giga workflow run review-change --workspace . --prompt \"Review this change\""
      : "giga schedule test-now weekday-review --workspace .";
  return (
    <section className="automation-starter-card">
      <div className="automation-starter-number">{starter.sequence}</div>
      <div>
        <span className="section-kicker">
          {locale === "ru" ? "Готовый пример" : "First-class example"}
        </span>
        <h3>{starter.title}</h3>
        <p>
          {locale === "ru"
            ? section === "agents"
              ? "Read-only Codex-агент, который возвращает конкретные замечания по коду."
              : section === "workflows"
                ? "Запускает Code Reviewer с повторно используемой задачей."
                : "Запускает Review Change по будням в отдельном worktree."
            : starter.description}
        </p>
      </div>
      <ol>
        <li>{locale === "ru" ? "Откройте пример и проверьте поля." : "Open the example and review its fields."}</li>
        <li>{locale === "ru" ? "Нажмите Preview change, затем Apply." : "Choose Preview change, then Apply."}</li>
        <li>
          {section === "schedules"
            ? locale === "ru"
              ? "Запустите Test schedule и только затем Enable."
              : "Run Test schedule before choosing Enable."
            : locale === "ru"
              ? "Запустите из карточки или той же CLI-командой."
              : "Run it from the detail card or with the same CLI contract."}
        </li>
      </ol>
      <code>{command}</code>
      <button className="primary-button" onClick={onCreate} type="button">
        {locale === "ru" ? `Создать ${starter.title}` : `Create ${starter.title}`}
      </button>
    </section>
  );
}

function AutomationRow({ item, section, selected }: {
  item: AgentProjection | WorkflowProjection | ScheduleProjection;
  section: AutomationSection;
  selected: boolean;
}) {
  const { preferences } = usePreferences();
  const locale = preferences.locale;
  const to = `/cockpit-v2/automation/${section}` as const;
  if (section === "agents") {
    const agent = item as AgentProjection;
    return <OperationalRowLink selected={selected} selectedId={agent.id} to={to}><div><strong>{agent.title}</strong><span>{agent.id}</span></div><span>{agent.harnessId}</span><span>{agent.model ?? message(locale, "defaultRoute")}</span><StatusBadge status={agent.mode} /></OperationalRowLink>;
  }
  if (section === "schedules") {
    const schedule = item as ScheduleProjection;
    return <OperationalRowLink selected={selected} selectedId={schedule.id} to={to}><div><strong>{schedule.title}</strong><span>{schedule.id}</span></div><span>{schedule.target}</span><span>{schedule.nextRunAt ?? "—"}</span><StatusBadge status={schedule.status} /></OperationalRowLink>;
  }
  const workflow = item as WorkflowProjection;
  return <OperationalRowLink selected={selected} selectedId={workflow.id} to={to}><div><strong>{workflow.title}</strong><span>{workflow.id}</span></div><span>{workflow.trigger}</span><span>{workflow.stepCount} {message(locale, "steps")}</span><StatusBadge status={workflow.lastRunStatus ?? "not run"} /></OperationalRowLink>;
}

function AutomationDetail({
  onAuthoring,
  section,
  selectedId,
}: {
  onAuthoring: (request: AutomationAuthoringRequest) => void;
  section: AutomationSection;
  selectedId: string | undefined;
}) {
  return (
    <AutomationDetailSelection
      key={`${section}:${selectedId ?? "none"}`}
      onAuthoring={onAuthoring}
      section={section}
      selectedId={selectedId}
    />
  );
}

function AutomationDetailSelection({
  onAuthoring,
  section,
  selectedId,
}: {
  onAuthoring: (request: AutomationAuthoringRequest) => void;
  section: AutomationSection;
  selectedId: string | undefined;
}) {
  const { preferences } = usePreferences();
  const locale = preferences.locale;
  const query = useQuery(automationSurfaceOptions());
  const queryClient = useQueryClient();
  const [prompt, setPrompt] = useState("");
  const submissionKey = useRef<string | null>(null);
  const selected = useMemo(() => query.data?.[section].find((item) => item.id === selectedId), [query.data, section, selectedId]);
  const plan = selected === undefined ? null : planAutomationAction(section, selected);
  const run = useMutation({
    mutationFn: async ({ key }: { key: string }) => {
      if (selected === undefined || plan === null) {
        throw new Error("Select an item first");
      }
      const itemId = encodeURIComponent(selected.id);
      let response: unknown;
      if (plan.kind === "agent_run") {
        response = await mutateCockpit(`/api/agents/${itemId}/run`, {
          idempotency_key: key,
          prompt: prompt.trim(),
        });
      } else if (plan.kind === "workflow_run") {
        response = await mutateCockpit(`/api/workflows/${itemId}/run`, {
          idempotency_key: key,
          ...(prompt.trim() ? { prompt: prompt.trim() } : {}),
        });
      } else {
        const action = plan.kind === "schedule_test" ? "test-now" : "run-now";
        response = await mutateCockpit(`/api/schedules/${itemId}/${action}`, {
          idempotency_key: key,
        });
      }
      return projectAutomationActionResult(response);
    },
    onSuccess: async (identity) => {
      submissionKey.current = null;
      const invalidations = [
        queryClient.invalidateQueries({ queryKey: remainingRequestKeys.automation() }),
      ];
      if (identity.runId || identity.sessionId || identity.workflowRunId) {
        invalidations.push(
          queryClient.invalidateQueries({ queryKey: requestKeys.runsCenter() }),
          queryClient.invalidateQueries({ queryKey: requestKeys.sessionIndex() }),
        );
      }
      if (identity.approvalId) {
        invalidations.push(
          queryClient.invalidateQueries({ queryKey: requestKeys.approvals() }),
        );
      }
      await Promise.all(invalidations);
    },
  });
  const lifecycle = useMutation({
    mutationFn: async (action: "enable" | "pause" | "resume") => {
      if (section !== "schedules" || selected === undefined) {
        throw new Error("Schedule lifecycle is unavailable.");
      }
      return mutateCockpit(`/api/schedules/${encodeURIComponent(selected.id)}/${action}`, {});
    },
    onSuccess: async (response) => {
      await queryClient.invalidateQueries({
        queryKey: remainingRequestKeys.automation(),
      });
      if (
        typeof response === "object" &&
        response !== null &&
        "approval_required" in response &&
        response.approval_required === true
      ) {
        openInbox("approvals");
      }
    },
  });

  if (selected === undefined) return <div className="detail-empty"><span className="section-kicker">{message(locale, "selectedDefinition")}</span><h2>{message(locale, "selectReusableDefinition")}</h2><p>{message(locale, "automationSelectionHint")}</p></div>;
  if (plan === null) return null;
  const promptMissing = plan.prompt === "required" && !prompt.trim();
  const disabledReason = plan.disabledReason;
  const disabledReasonText =
    disabledReason === "worker_offline"
      ? message(locale, "workerOfflineRecovery")
      : disabledReason;
  const submit = () => {
    if (run.isPending || disabledReason !== null || promptMissing) return;
    submissionKey.current ??= createAutomationSubmissionKey(section, selected.id);
    run.mutate({ key: submissionKey.current });
  };
  const updatePrompt = (value: string) => {
    if (value !== prompt && run.isError) {
      submissionKey.current = null;
      run.reset();
    }
    setPrompt(value);
  };
  return (
    <div className="definition-detail">
      <span className="section-kicker">{message(locale, "selectedDefinition")}</span>
      <h2>{selected.title}</h2>
      <code>{selected.id}</code>
      <dl className="compact-fields">
        {Object.entries(selected).filter(([key]) => !["id", "title", "queueable", "tested", "unavailableReason"].includes(key)).slice(0, 5).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{value === null ? "—" : String(value)}</dd></div>)}
      </dl>
      {plan.prompt !== "none" ? <label className="field-control">{message(locale, plan.prompt === "required" ? "runPrompt" : "optionalRunPrompt")}<textarea value={prompt} onChange={(event) => updatePrompt(event.target.value)} placeholder={message(locale, "composerPlaceholder")} /></label> : null}
      {disabledReasonText ? <p className="action-unavailable" role="note">{message(locale, "actionUnavailable")} {disabledReasonText}</p> : null}
      <button className="primary-button" disabled={run.isPending || disabledReason !== null || promptMissing} onClick={submit} type="button">{message(locale, run.isPending ? "loading" : plan.labelKey)}</button>
      <div className="definition-authoring-actions">
        <button onClick={() => onAuthoring({ mode: "edit", section, id: selected.id })} type="button">{message(locale, "authoringEdit")}</button>
        <button onClick={() => onAuthoring({ mode: "duplicate", section, id: selected.id })} type="button">{message(locale, "authoringDuplicate")}</button>
        <button className="danger-button" onClick={() => onAuthoring({ mode: "delete", section, id: selected.id })} type="button">{message(locale, "authoringDelete")}</button>
      </div>
      {section === "schedules" ? (
        <div className="definition-lifecycle-actions">
          <button disabled={lifecycle.isPending} onClick={() => lifecycle.mutate("enable")} type="button">{message(locale, "enableDefinition")}</button>
          <button disabled={lifecycle.isPending} onClick={() => lifecycle.mutate("pause")} type="button">{message(locale, "pauseDefinition")}</button>
          <button disabled={lifecycle.isPending} onClick={() => lifecycle.mutate("resume")} type="button">{message(locale, "resumeDefinition")}</button>
        </div>
      ) : null}
      {run.isError ? <p className="mutation-error" role="alert">{run.error.message}</p> : null}
      {lifecycle.isError ? <p className="mutation-error" role="alert">{lifecycle.error.message}</p> : null}
      {run.isSuccess ? <AutomationActionReceipt identity={run.data} /> : null}
    </div>
  );
}

function AutomationActionReceipt({
  identity,
}: {
  identity: ReturnType<typeof projectAutomationActionResult>;
}) {
  const { preferences } = usePreferences();
  const locale = preferences.locale;
  const exactId = identity.runId ?? identity.workflowRunId ?? identity.occurrenceId ?? identity.approvalId;
  return (
    <section className="automation-action-receipt" role="status">
      <strong>{message(locale, identity.approvalId ? "approvalRequired" : "operationAccepted")}</strong>
      {exactId ? <code>{exactId}</code> : null}
      <div className="automation-action-links">
        {identity.runId ? <Link params={{ runId: identity.runId }} to="/cockpit-v2/runs/$runId">{message(locale, "openRun")}</Link> : null}
        {!identity.runId && identity.sessionId ? <Link params={{ sessionId: identity.sessionId }} to="/cockpit-v2/work/$sessionId">{message(locale, "openSession")}</Link> : null}
        {identity.approvalId ? <button onClick={() => openInbox("approvals")} type="button">{message(locale, "reviewApproval")}</button> : null}
      </div>
    </section>
  );
}

function openInbox(tab: string) {
  globalThis.dispatchEvent(new CustomEvent("cockpit:open-inbox", { detail: tab }));
}
