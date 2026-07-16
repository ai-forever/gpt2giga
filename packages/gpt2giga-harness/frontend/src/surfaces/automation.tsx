import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from "@tanstack/react-query";
import { useRouterState, useSearch } from "@tanstack/react-router";
import { useMemo, useState } from "react";

import { mutateCockpit } from "../api";
import {
  LoadingRows,
  OperationalRowLink,
  OperationalSurface,
  StatusBadge,
  type OperationalTab,
} from "../components/OperationalSurface";
import { message } from "../messages";
import { usePreferences } from "../preferences-context";
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

  return (
    <OperationalSurface
      activeTab={section}
      aside={<AutomationDetail section={section} selectedId={selectedId} />}
      detailKey="automationDetailMigrated"
      eyebrowKey="automationEyebrow"
      tabs={tabs}
      titleKey="automation"
    >
      <AutomationList section={section} query={query} selectedId={selectedId} />
    </OperationalSurface>
  );
}

function AutomationList({ section, query, selectedId }: {
  section: "agents" | "workflows" | "schedules";
  query: UseQueryResult<AutomationProjection, Error>;
  selectedId: string | undefined;
}) {
  const { preferences } = usePreferences();
  const locale = preferences.locale;
  if (query.isPending) return <LoadingRows />;
  if (query.isError || query.data === undefined) {
    return <div className="error-state">{message(locale, "boundedDataUnavailable")}</div>;
  }
  const rows = query.data[section];
  return (
    <>
      <div className="operations-toolbar">
        <div>
          <span className="section-kicker">{message(locale, section)}</span>
          <strong>{rows.length} {message(locale, "retainedItems")}</strong>
        </div>
        <a className="primary-link" data-legacy-transition="true" href={section === "agents" ? "/agents" : section === "schedules" ? "/scheduled" : "/workflows"}>
          {message(locale, "openLegacyAuthoring")}
        </a>
      </div>
      {rows.length === 0 ? (
        <div className="empty-state">{message(locale, "noItems")}</div>
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

function AutomationRow({ item, section, selected }: {
  item: AgentProjection | WorkflowProjection | ScheduleProjection;
  section: "agents" | "workflows" | "schedules";
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

function AutomationDetail({ section, selectedId }: { section: "agents" | "workflows" | "schedules"; selectedId: string | undefined }) {
  const { preferences } = usePreferences();
  const locale = preferences.locale;
  const query = useQuery(automationSurfaceOptions());
  const queryClient = useQueryClient();
  const [prompt, setPrompt] = useState("");
  const selected = useMemo(() => query.data?.[section].find((item) => item.id === selectedId), [query.data, section, selectedId]);
  const run = useMutation({
    mutationFn: async () => {
      if (selected === undefined) throw new Error("Select an item first");
      if (section === "agents") {
        if (!prompt.trim()) throw new Error(message(locale, "promptRequired"));
        return mutateCockpit(`/api/agents/${encodeURIComponent(selected.id)}/run`, { prompt: prompt.trim() });
      }
      if (section === "schedules") return mutateCockpit(`/api/schedules/${encodeURIComponent(selected.id)}/run-now`, {});
      return mutateCockpit(`/api/workflows/${encodeURIComponent(selected.id)}/run`, {});
    },
    onSuccess: async () => queryClient.invalidateQueries({ queryKey: remainingRequestKeys.automation() }),
  });

  if (selected === undefined) return <div className="detail-empty"><span className="section-kicker">{message(locale, "selectedDefinition")}</span><h2>{message(locale, "selectReusableDefinition")}</h2><p>{message(locale, "automationSelectionHint")}</p></div>;
  return (
    <div className="definition-detail">
      <span className="section-kicker">{message(locale, "selectedDefinition")}</span>
      <h2>{selected.title}</h2>
      <code>{selected.id}</code>
      <dl className="compact-fields">
        {Object.entries(selected).filter(([key]) => !["id", "title"].includes(key)).slice(0, 5).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{value === null ? "—" : String(value)}</dd></div>)}
      </dl>
      {section === "agents" ? <label className="field-control">{message(locale, "runPrompt")}<textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder={message(locale, "composerPlaceholder")} /></label> : null}
      <button className="primary-button" disabled={run.isPending} onClick={() => run.mutate()} type="button">{message(locale, run.isPending ? "loading" : "runNow")}</button>
      {run.isError ? <p className="mutation-error" role="alert">{run.error.message}</p> : null}
      {run.isSuccess ? <p className="mutation-success" role="status">{message(locale, "runQueued")}</p> : null}
    </div>
  );
}
