import { useMutation, useQuery, type UseQueryResult } from "@tanstack/react-query";
import { useRouterState, useSearch } from "@tanstack/react-router";
import { useMemo, useState } from "react";

import { fetchCockpit, mutateCockpit } from "../api";
import {
  LoadingRows,
  OperationalRowLink,
  OperationalSurface,
  StatusBadge,
  type OperationalTab,
} from "../components/OperationalSurface";
import { message } from "../messages";
import { usePreferences } from "../preferences-context";
import { integrationsSurfaceOptions } from "../remaining-request-graph";
import { projectDoctor, type DoctorProjection, type HarnessProjection, type IntegrationsProjection } from "../surface-projections";

interface HandoffPreviewResponse {
  handoff: {
    action: string;
    status: string;
    surface: string;
    command: string[];
    workspace: string;
    ownership: string;
    auth_prerequisite: string;
    observability_limits: string[];
    external_process_may_open: boolean;
    external_ui_may_open: boolean;
    instruction: string;
    blocker: string | null;
    queueable: false;
    durable: false;
  };
}

const tabs: readonly OperationalTab[] = [
  { id: "harnesses", labelKey: "harnesses", href: "/cockpit-v2/integrations/harnesses" },
  { id: "models", labelKey: "modelsAndRoutes", href: "/cockpit-v2/integrations/models" },
  { id: "mcp", labelKey: "mcp", href: "/cockpit-v2/integrations/mcp" },
  { id: "doctor", labelKey: "doctor", href: "/cockpit-v2/integrations/doctor" },
];

export function IntegrationsSurface() {
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const section = pathname.endsWith("/models") ? "models" : pathname.endsWith("/mcp") ? "mcp" : pathname.endsWith("/doctor") ? "doctor" : "harnesses";
  const { selected: selectedId } = useSearch({ strict: false });
  const query = useQuery(integrationsSurfaceOptions());
  return (
    <OperationalSurface
      activeTab={section}
      aside={<IntegrationDetail section={section} selectedId={selectedId} />}
      detailKey="integrationsDetailMigrated"
      eyebrowKey="integrationsEyebrow"
      tabs={tabs}
      titleKey="integrations"
    >
      <IntegrationList section={section} query={query} selectedId={selectedId} />
    </OperationalSurface>
  );
}

function IntegrationList({ section, query, selectedId }: {
  section: "harnesses" | "models" | "mcp" | "doctor";
  query: UseQueryResult<IntegrationsProjection, Error>;
  selectedId: string | undefined;
}) {
  const { preferences } = usePreferences();
  const locale = preferences.locale;
  if (query.isPending) return <LoadingRows />;
  if (query.isError || query.data === undefined) return <div className="error-state">{message(locale, "boundedDataUnavailable")}</div>;
  if (section === "doctor") return <div className="doctor-intro"><span className="section-kicker">{message(locale, "selectedPlanDoctor")}</span><h2>{message(locale, "doctorTitle")}</h2><p>{message(locale, "doctorDescription")}</p></div>;
  const rows = section === "models" ? query.data.routes : query.data[section];
  return (
    <>
      <div className="operations-toolbar"><div><span className="section-kicker">{message(locale, section === "models" ? "modelsAndRoutes" : section)}</span><strong>{rows.length} {message(locale, "retainedItems")}</strong></div></div>
      {rows.length === 0 ? <div className="empty-state">{message(locale, "noItems")}</div> : <div className="operations-table" role="table">
        {section === "harnesses" ? query.data.harnesses.map((item) => <OperationalRowLink selected={selectedId === item.id} selectedId={item.id} to="/cockpit-v2/integrations/harnesses" key={item.id}><div><strong>{item.title}</strong><span>{item.id}</span></div><span>{item.kind}</span><span>{item.reason}</span><StatusBadge status={item.status} /></OperationalRowLink>) : null}
        {section === "models" ? query.data.routes.map((item) => <OperationalRowLink selected={selectedId === item.id} selectedId={item.id} to="/cockpit-v2/integrations/models" key={item.id}><div><strong>{item.chatEndpoint}</strong><span>{item.configuredDefault ? message(locale, "configuredDefault") : message(locale, "availableRoute")}</span></div><span>{item.effectiveModel ?? message(locale, "notSelected")}</span><span>{routeSourceLabel(locale, item.effectiveSource)}</span><StatusBadge status={item.health} /></OperationalRowLink>) : null}
        {section === "mcp" ? query.data.mcp.map((item) => <OperationalRowLink selected={selectedId === item.id} selectedId={item.id} to="/cockpit-v2/integrations/mcp" key={item.id}><div><strong>{item.title}</strong><span>{item.id}</span></div><span>{item.transport}</span><span>{item.trusted ? message(locale, "trusted") : message(locale, "reviewRequired")}</span><StatusBadge status={item.status} /></OperationalRowLink>) : null}
      </div>}
    </>
  );
}

function IntegrationDetail({ section, selectedId }: { section: "harnesses" | "models" | "mcp" | "doctor"; selectedId: string | undefined }) {
  const { preferences } = usePreferences();
  const locale = preferences.locale;
  const query = useQuery(integrationsSurfaceOptions());
  const [doctor, setDoctor] = useState<DoctorProjection | null>(null);
  const [doctorHarness, setDoctorHarness] = useState("echo");
  const selected = useMemo(() => {
    if (section === "harnesses") return query.data?.harnesses.find((item) => item.id === selectedId);
    if (section === "models") return query.data?.routes.find((item) => item.apiMode === selectedId);
    if (section === "mcp") return query.data?.mcp.find((item) => item.id === selectedId);
    return undefined;
  }, [query.data, section, selectedId]);
  const doctorMutation = useMutation({
    mutationFn: () => mutateCockpit<unknown>("/api/preflight/run", { api_mode: query.data?.routes.find((item) => item.configuredDefault)?.apiMode ?? "v2", dry_run: true, durable: false, harness_id: doctorHarness, invocation_mode: "headless", mode: "plan", prompt: "Readiness check", workspace_policy: "auto" }),
    onSuccess: (response) => setDoctor(projectDoctor(response)),
  });
  const probeMutation = useMutation({
    mutationFn: () => selected !== undefined && "transport" in selected ? mutateCockpit(`/api/tool-servers/${encodeURIComponent(selected.id)}/probe`, {}) : Promise.reject(new Error("Select an MCP server first")),
  });
  if (section === "doctor") return <div className="definition-detail"><span className="section-kicker">{message(locale, "doctor")}</span><h2>{message(locale, "selectedPlanReadiness")}</h2><label className="field-control">{message(locale, "harness")}<select value={doctorHarness} onChange={(event) => setDoctorHarness(event.target.value)}>{query.data?.harnesses.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}</select></label><button className="primary-button" disabled={doctorMutation.isPending} onClick={() => doctorMutation.mutate()} type="button">{message(locale, "runDoctor")}</button>{doctor === null ? null : <div className="doctor-result" role="status"><StatusBadge status={doctor.status} /><p><strong>{doctor.status === "ready" ? message(locale, "ready") : doctor.status}</strong> · {doctorEvidenceLabel(locale, doctor.evidenceStatus)}</p><p>{doctor.harnessId}</p>{doctor.findings.filter((item) => item.status !== "ready").map((item) => <div className="doctor-finding" key={item.id}><strong>{item.summary}</strong>{item.remedy ? <span>{item.remedy}</span> : null}{item.command ? <code>{item.command}</code> : null}</div>)}</div>}{doctorMutation.isError ? <p className="mutation-error" role="alert">{doctorMutation.error.message}</p> : null}</div>;
  if (selected === undefined) return <div className="detail-empty"><span className="section-kicker">{message(locale, "selectedIntegration")}</span><h2>{message(locale, "selectIntegration")}</h2><p>{message(locale, "integrationSelectionHint")}</p></div>;
  if (section === "harnesses" && "executionSurfaces" in selected) return <HarnessDetail harness={selected} key={selected.id} />;
  if (section === "models" && "chatEndpoint" in selected) return <div className="definition-detail"><span className="section-kicker">{message(locale, "selectedIntegration")}</span><h2>{selected.chatEndpoint}</h2><dl className="compact-fields"><div><dt>{message(locale, "apiMode")}</dt><dd>{selected.apiMode}</dd></div><div><dt>{message(locale, "configuredDefault")}</dt><dd>{selected.configuredDefault ? message(locale, "yes") : message(locale, "no")}</dd></div><div><dt>{message(locale, "effectiveSelection")}</dt><dd>{selected.effectiveModel ?? message(locale, "notSelected")}</dd></div><div><dt>{message(locale, "source")}</dt><dd>{routeSourceLabel(locale, selected.effectiveSource)}</dd></div><div><dt>{message(locale, "modelsEndpoint")}</dt><dd>{selected.modelsEndpoint}</dd></div><div><dt>{message(locale, "discoveredModels")}</dt><dd>{selected.discoveredModels.join(", ") || message(locale, "noDiscoveredModels")}</dd></div><div><dt>{message(locale, "discoverySource")}</dt><dd>{selected.discoverySource}</dd></div><div><dt>{message(locale, "lastChecked")}</dt><dd>{selected.lastCheckedAt ?? message(locale, "notChecked")}</dd></div></dl></div>;
  return <div className="definition-detail"><span className="section-kicker">{message(locale, "selectedIntegration")}</span><h2>{"title" in selected ? selected.title : `/${selected.apiMode}`}</h2><dl className="compact-fields">{Object.entries(selected).slice(0, 7).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{String(value)}</dd></div>)}</dl>{section === "mcp" ? <button disabled={probeMutation.isPending || !("enabled" in selected) || !selected.enabled} onClick={() => probeMutation.mutate()} type="button">{message(locale, "probeMcp")}</button> : null}{probeMutation.isError ? <p className="mutation-error" role="alert">{probeMutation.error.message}</p> : null}{probeMutation.isSuccess ? <p className="mutation-success" role="status">{message(locale, "operationAccepted")}</p> : null}</div>;
}

function HarnessDetail({ harness }: { harness: HarnessProjection }) {
  const { preferences } = usePreferences();
  const locale = preferences.locale;
  const [action, setAction] = useState(harness.handoffActions[0] ?? "launch_new");
  const preview = useMutation({
    mutationFn: () => fetchCockpit<HandoffPreviewResponse>(
      `/api/provider-handoffs/${encodeURIComponent(harness.id)}/preview?action=${encodeURIComponent(action)}&workspace=.`,
    ),
  });
  return <div className="definition-detail harness-execution-detail">
    <span className="section-kicker">{message(locale, "selectedIntegration")}</span>
    <h2>{harness.title}</h2>
    <p>{harness.reason}</p>
    <h3>{message(locale, "executionSurfaces")}</h3>
    <div className="execution-surface-list">
      {harness.executionSurfaces.map((surface) => <div className="execution-surface-card" key={surface.id}>
        <div><strong>{executionSurfaceLabel(locale, surface.id)}</strong><StatusBadge status={surface.status} /></div>
        <p>{surface.detail}</p>
        <small>{surface.ownership} · {surface.queueable ? message(locale, "queueable") : message(locale, "notQueueable")}</small>
        {surface.blocker ? <code>{surface.blocker}</code> : null}
      </div>)}
    </div>
    {harness.handoffActions.length === 0 ? null : <section className="handoff-preview-panel">
      <h3>{message(locale, "providerHandoff")}</h3>
      <p>{message(locale, "handoffDescription")}</p>
      <label className="field-control">{message(locale, "handoffAction")}
        <select value={action} onChange={(event) => { setAction(event.target.value); preview.reset(); }}>
          {harness.handoffActions.map((item) => <option key={item} value={item}>{handoffActionLabel(locale, item)}</option>)}
        </select>
      </label>
      <button className="primary-button" disabled={preview.isPending} onClick={() => preview.mutate()} type="button">{message(locale, "previewHandoff")}</button>
      {preview.isError ? <p className="mutation-error" role="alert">{preview.error.message}</p> : null}
      {preview.data ? <div className="handoff-preview-result" role="status">
        <StatusBadge status={preview.data.handoff.status} />
        <p>{preview.data.handoff.instruction}</p>
        {preview.data.handoff.command.length > 0 ? <code>{preview.data.handoff.command.join(" ")}</code> : null}
        <dl className="compact-fields">
          <div><dt>{message(locale, "workspace")}</dt><dd>{preview.data.handoff.workspace}</dd></div>
          <div><dt>{message(locale, "ownership")}</dt><dd>{preview.data.handoff.ownership}</dd></div>
          <div><dt>{message(locale, "authentication")}</dt><dd>{preview.data.handoff.auth_prerequisite}</dd></div>
          <div><dt>{message(locale, "durable")}</dt><dd>{message(locale, "no")}</dd></div>
        </dl>
      </div> : null}
    </section>}
  </div>;
}

function executionSurfaceLabel(locale: "en" | "ru", id: string) {
  if (id === "one_shot") return message(locale, "oneShot");
  if (id === "native_terminal") return message(locale, "nativeTerminal");
  if (id === "provider_handoff") return message(locale, "providerHandoff");
  if (id === "native_structured_embedded") return message(locale, "embeddedStructured");
  return id;
}

function handoffActionLabel(locale: "en" | "ru", action: string) {
  if (action === "launch_new") return message(locale, "launchNew");
  if (action === "attach_current") return message(locale, "attachCurrent");
  if (action === "open_provider_ui") return message(locale, "openProviderUi");
  if (action === "disconnect") return message(locale, "disconnect");
  if (action === "stop") return message(locale, "stop");
  return action;
}

function routeSourceLabel(locale: "en" | "ru", source: string) {
  if (source === "environment") return message(locale, "environmentDefault");
  if (source === "harness_settings") return message(locale, "harnessSettingsSource");
  if (source === "built_in") return message(locale, "builtInFallback");
  if (source === "not_selected") return message(locale, "notSelected");
  return message(locale, "unknownSource");
}

function doctorEvidenceLabel(locale: "en" | "ru", status: DoctorProjection["evidenceStatus"]) {
  if (status === "not_checked") return message(locale, "routeNotChecked");
  if (status === "unknown") return message(locale, "routeEvidenceUnknown");
  return message(locale, "routeEvidenceObserved");
}
