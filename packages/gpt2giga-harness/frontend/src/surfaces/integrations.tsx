import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";
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
import {
  integrationFlowOptions,
  integrationsSurfaceOptions,
  remainingRequestKeys,
  type IntegrationFlowMutationResponse,
  type IntegrationFlowPreviewResponse,
} from "../remaining-request-graph";
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
  { id: "add", labelKey: "addIntegration", href: "/cockpit-v2/integrations/add" },
  { id: "harnesses", labelKey: "harnesses", href: "/cockpit-v2/integrations/harnesses" },
  { id: "models", labelKey: "modelsAndRoutes", href: "/cockpit-v2/integrations/models" },
  { id: "mcp", labelKey: "mcp", href: "/cockpit-v2/integrations/mcp" },
  { id: "doctor", labelKey: "doctor", href: "/cockpit-v2/integrations/doctor" },
];

type IntegrationSection = "add" | "harnesses" | "models" | "mcp" | "doctor";

export function IntegrationsSurface() {
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const section: IntegrationSection = pathname.endsWith("/add") ? "add" : pathname.endsWith("/models") ? "models" : pathname.endsWith("/mcp") ? "mcp" : pathname.endsWith("/doctor") ? "doctor" : "harnesses";
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
  section: IntegrationSection;
  query: UseQueryResult<IntegrationsProjection, Error>;
  selectedId: string | undefined;
}) {
  const { preferences } = usePreferences();
  const locale = preferences.locale;
  if (section === "add") return <IntegrationWizard />;
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

function IntegrationDetail({ section, selectedId }: { section: IntegrationSection; selectedId: string | undefined }) {
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
  if (section === "add") return <RecentIntegrationFlows />;
  if (section === "doctor") return <div className="definition-detail"><span className="section-kicker">{message(locale, "doctor")}</span><h2>{message(locale, "selectedPlanReadiness")}</h2><label className="field-control">{message(locale, "harness")}<select value={doctorHarness} onChange={(event) => setDoctorHarness(event.target.value)}>{query.data?.harnesses.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}</select></label><button className="primary-button" disabled={doctorMutation.isPending} onClick={() => doctorMutation.mutate()} type="button">{message(locale, "runDoctor")}</button>{doctor === null ? null : <div className="doctor-result" role="status"><StatusBadge status={doctor.status} /><p><strong>{doctor.status === "ready" ? message(locale, "ready") : doctor.status}</strong> · {doctorEvidenceLabel(locale, doctor.evidenceStatus)}</p><p>{doctor.harnessId}</p>{doctor.findings.filter((item) => item.status !== "ready").map((item) => <div className="doctor-finding" key={item.id}><strong>{item.summary}</strong>{item.remedy ? <span>{item.remedy}</span> : null}{item.command ? <code>{item.command}</code> : null}</div>)}</div>}{doctorMutation.isError ? <p className="mutation-error" role="alert">{doctorMutation.error.message}</p> : null}</div>;
  if (selected === undefined) return <div className="detail-empty"><span className="section-kicker">{message(locale, "selectedIntegration")}</span><h2>{message(locale, "selectIntegration")}</h2><p>{message(locale, "integrationSelectionHint")}</p></div>;
  if (section === "harnesses" && "executionSurfaces" in selected) return <HarnessDetail harness={selected} key={selected.id} />;
  if (section === "models" && "chatEndpoint" in selected) return <div className="definition-detail"><span className="section-kicker">{message(locale, "selectedIntegration")}</span><h2>{selected.chatEndpoint}</h2><dl className="compact-fields"><div><dt>{message(locale, "apiMode")}</dt><dd>{selected.apiMode}</dd></div><div><dt>{message(locale, "configuredDefault")}</dt><dd>{selected.configuredDefault ? message(locale, "yes") : message(locale, "no")}</dd></div><div><dt>{message(locale, "effectiveSelection")}</dt><dd>{selected.effectiveModel ?? message(locale, "notSelected")}</dd></div><div><dt>{message(locale, "source")}</dt><dd>{routeSourceLabel(locale, selected.effectiveSource)}</dd></div><div><dt>{message(locale, "modelsEndpoint")}</dt><dd>{selected.modelsEndpoint}</dd></div><div><dt>{message(locale, "discoveredModels")}</dt><dd>{selected.discoveredModels.join(", ") || message(locale, "noDiscoveredModels")}</dd></div><div><dt>{message(locale, "discoverySource")}</dt><dd>{selected.discoverySource}</dd></div><div><dt>{message(locale, "lastChecked")}</dt><dd>{selected.lastCheckedAt ?? message(locale, "notChecked")}</dd></div></dl></div>;
  return <div className="definition-detail"><span className="section-kicker">{message(locale, "selectedIntegration")}</span><h2>{"title" in selected ? selected.title : `/${selected.apiMode}`}</h2><dl className="compact-fields">{Object.entries(selected).slice(0, 7).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{String(value)}</dd></div>)}</dl>{section === "mcp" ? <button disabled={probeMutation.isPending || !("enabled" in selected) || !selected.enabled} onClick={() => probeMutation.mutate()} type="button">{message(locale, "probeMcp")}</button> : null}{probeMutation.isError ? <p className="mutation-error" role="alert">{probeMutation.error.message}</p> : null}{probeMutation.isSuccess ? <p className="mutation-success" role="status">{message(locale, "operationAccepted")}</p> : null}</div>;
}

function IntegrationWizard() {
  const { preferences } = usePreferences();
  const locale = preferences.locale;
  const queryClient = useQueryClient();
  const inventory = useQuery(integrationFlowOptions());
  const [source, setSource] = useState("catalog");
  const [catalogId, setCatalogId] = useState("");
  const [targetId, setTargetId] = useState("");
  const [scope, setScope] = useState("");
  const [packageId, setPackageId] = useState("custom-mcp");
  const [transport, setTransport] = useState("stdio");
  const [command, setCommand] = useState("custom-mcp");
  const [manifestJson, setManifestJson] = useState("{}");
  const [authority, setAuthority] = useState("cockpit-operator");
  const [allowNetwork, setAllowNetwork] = useState(false);
  const [nativeConsent, setNativeConsent] = useState(false);
  const selectedCatalog = inventory.data?.catalog.find((item) => item.catalog_id === catalogId) ?? inventory.data?.catalog[0];
  const targets = inventory.data?.targets.filter((item) => source !== "catalog" || selectedCatalog?.target_ids.includes(item.id)) ?? [];
  const selectedTarget = targets.find((item) => item.id === targetId) ?? targets[0];
  const selectedScope = selectedTarget?.scopes.includes(scope) ? scope : selectedTarget?.scopes[0] ?? "managed_home";
  const selectedCatalogId = selectedCatalog?.catalog_id ?? "";

  const preview = useMutation({
    mutationFn: () => {
      let manifest: unknown = undefined;
      if (!["catalog", "raw_descriptor"].includes(source)) manifest = JSON.parse(manifestJson);
      return mutateCockpit<IntegrationFlowPreviewResponse>("/api/integrations/preview", {
        source,
        catalog_id: source === "catalog" ? selectedCatalogId : undefined,
        manifest,
        target_id: selectedTarget?.id,
        scope: selectedScope,
        package_id: source === "raw_descriptor" ? packageId : undefined,
        configuration: source === "raw_descriptor" ? {
          transport,
          command: transport === "stdio" ? command : undefined,
          url: transport === "stdio" ? undefined : command,
        } : {},
      });
    },
  });
  const apply = useMutation({
    mutationFn: () => {
      if (!preview.data) throw new Error("Preview an integration first");
      return mutateCockpit<IntegrationFlowMutationResponse>(
        `/api/integrations/flows/${encodeURIComponent(preview.data.flow.id)}/apply`,
        {
          plan_id: preview.data.plan.plan_id,
          authority,
          allow_network: allowNetwork,
          native_consent_acknowledged: nativeConsent,
        },
      );
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: remainingRequestKeys.integrationFlows() });
    },
  });
  const rollback = useMutation({
    mutationFn: () => {
      const flow = apply.data?.flow ?? preview.data?.flow;
      if (!flow) throw new Error("No integration operation to roll back");
      return mutateCockpit<IntegrationFlowMutationResponse>(
        `/api/integrations/flows/${encodeURIComponent(flow.id)}/rollback`,
        {},
      );
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: remainingRequestKeys.integrationFlows() });
    },
  });

  if (inventory.isPending) return <LoadingRows />;
  if (inventory.isError || !inventory.data) return <div className="error-state">{message(locale, "boundedDataUnavailable")}</div>;
  const flow = rollback.data?.flow ?? apply.data?.flow ?? preview.data?.flow;
  return <div className="integration-wizard">
    <div className="operations-toolbar"><div><span className="section-kicker">MCP + · Skill + · Plugin + · Harness +</span><strong>{message(locale, "addIntegration")}</strong></div></div>
    <p className="wizard-description">{message(locale, "addIntegrationDescription")}</p>
    <div className="wizard-fields">
      <label className="field-control">{message(locale, "source")}<select value={source} onChange={(event) => { setSource(event.target.value); preview.reset(); apply.reset(); }}>{inventory.data.sources.map((item) => <option key={item.id} value={item.id}>{sourceLabel(item.id)}</option>)}</select></label>
      {source === "catalog" ? <label className="field-control">{message(locale, "catalogEntry")}<select value={selectedCatalogId} onChange={(event) => { setCatalogId(event.target.value); setTargetId(""); preview.reset(); }}><option disabled value="">{message(locale, "selectCatalogEntry")}</option>{inventory.data.catalog.map((item) => <option key={item.catalog_id} value={item.catalog_id}>{item.package_id} · {item.version}</option>)}</select></label> : null}
      {!["catalog", "raw_descriptor"].includes(source) ? <label className="field-control span-two">{message(locale, "packageManifest")}<textarea value={manifestJson} onChange={(event) => setManifestJson(event.target.value)} spellCheck={false} /></label> : null}
      {source === "raw_descriptor" ? <><label className="field-control">{message(locale, "packageId")}<input value={packageId} onChange={(event) => setPackageId(event.target.value)} /></label><label className="field-control">{message(locale, "transport")}<select value={transport} onChange={(event) => setTransport(event.target.value)}><option value="stdio">stdio</option><option value="streamable_http">streamable HTTP</option><option value="sse">SSE</option></select></label><label className="field-control span-two">{transport === "stdio" ? message(locale, "command") : "HTTPS URL"}<input value={command} onChange={(event) => setCommand(event.target.value)} /></label></> : null}
      <label className="field-control">{message(locale, "target")}<select value={selectedTarget?.id ?? ""} onChange={(event) => { setTargetId(event.target.value); setScope(""); preview.reset(); }}>{targets.map((item) => <option key={item.id} value={item.id}>{item.id}</option>)}</select></label>
      <label className="field-control">{message(locale, "scope")}<select value={selectedScope} onChange={(event) => { setScope(event.target.value); preview.reset(); }}>{selectedTarget?.scopes.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
    </div>
    <button className="primary-button" disabled={preview.isPending || !selectedTarget} onClick={() => { apply.reset(); rollback.reset(); preview.mutate(); }} type="button">{message(locale, "previewInstall")}</button>
    {preview.isError ? <p className="mutation-error" role="alert">{preview.error.message}</p> : null}
    {preview.data ? <section className="integration-preview" aria-label={message(locale, "previewInstall")}>
      <div className="integration-preview-heading"><div><span className="section-kicker">{message(locale, "approvalRequired")}</span><h2>{preview.data.plan.package.id} · {preview.data.plan.target.id}</h2></div><StatusBadge status={preview.data.plan.risk.decision} /></div>
      <dl className="compact-fields"><div><dt>{message(locale, "publisher")}</dt><dd>{preview.data.plan.package.publisher}</dd></div><div><dt>{message(locale, "license")}</dt><dd>{preview.data.plan.package.license}</dd></div><div><dt>{message(locale, "checksum")}</dt><dd>{preview.data.plan.package.checksum}</dd></div><div><dt>{message(locale, "permissions")}</dt><dd>{preview.data.plan.permissions.requirements.map((item) => item.type).join(", ") || "none"}</dd></div><div><dt>{message(locale, "configurationDiff")}</dt><dd>{preview.data.plan.configuration.diff.join(", ") || "no file changes"}</dd></div><div><dt>{message(locale, "verification")}</dt><dd>{preview.data.plan.verification_steps.join(", ")}</dd></div><div><dt>{message(locale, "restartRequired")}</dt><dd>{preview.data.plan.configuration.restart_required ? message(locale, "yes") : message(locale, "no")}</dd></div></dl>
      <label className="field-control">{message(locale, "approvalAuthority")}<input value={authority} onChange={(event) => setAuthority(event.target.value)} /></label>
      {preview.data.plan.permissions.network ? <label className="check-control"><input checked={allowNetwork} onChange={(event) => setAllowNetwork(event.target.checked)} type="checkbox" />{message(locale, "allowNetwork")}</label> : null}
      {preview.data.plan.permissions.native_consent ? <label className="check-control"><input checked={nativeConsent} onChange={(event) => setNativeConsent(event.target.checked)} type="checkbox" />{message(locale, "nativeConsent")}</label> : null}
      <div className="wizard-actions"><button className="primary-button" disabled={apply.isPending || !authority.trim()} onClick={() => apply.mutate()} type="button">{message(locale, "approveAndApply")}</button>{flow?.rollback_available ? <button disabled={rollback.isPending} onClick={() => rollback.mutate()} type="button">{message(locale, "rollback")}</button> : null}</div>
      {apply.isError ? <p className="mutation-error" role="alert">{apply.error.message}</p> : null}
      {rollback.isError ? <p className="mutation-error" role="alert">{rollback.error.message}</p> : null}
      {flow ? <p className="flow-status" role="status"><strong>{message(locale, "flowStatus")}:</strong> {flow.status} · {flow.verification_status}</p> : null}
      {apply.data?.handoff ? <p className="handoff-notice">{message(locale, "providerOwnedHandoff")}</p> : null}
    </section> : null}
  </div>;
}

function RecentIntegrationFlows() {
  const { preferences } = usePreferences();
  const locale = preferences.locale;
  const inventory = useQuery(integrationFlowOptions());
  if (inventory.isPending) return <LoadingRows />;
  if (inventory.isError || !inventory.data) return <div className="error-state">{message(locale, "boundedDataUnavailable")}</div>;
  return <div className="definition-detail"><span className="section-kicker">{message(locale, "recentOperations")}</span><h2>{message(locale, "flowStatus")}</h2>{inventory.data.flows.length === 0 ? <p>{message(locale, "noOperations")}</p> : <div className="flow-list">{inventory.data.flows.slice(0, 8).map((flow) => <article key={flow.id}><div><strong>{flow.package_id}</strong><StatusBadge status={flow.status} /></div><small>{flow.target_id} · {flow.scope}</small><span>{flow.verification_status}</span></article>)}</div>}</div>;
}

function sourceLabel(source: string) {
  return ({ catalog: "Curated catalog", marketplace: "Provider marketplace", git: "Git + immutable ref", local: "Local path", package: "Package reference", raw_descriptor: "Raw MCP descriptor" } as Record<string, string>)[source] ?? source;
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
