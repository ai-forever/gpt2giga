import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  fetchCockpit,
  patchCockpit,
  type ModelsResponse,
  type SettingsResponse,
  type SettingsSaveResponse,
  withQuery,
} from "../api";
import { LazyInspector, type InspectorKind } from "../inspectors/LazyInspector";
import { message } from "../messages";
import type { LocalePreference, ThemePreference } from "../preferences";
import { usePreferences } from "../preferences-context";
import { requestKeys, settingsOptions } from "../request-graph";

type DefaultsDraft = {
  default_api_mode: string;
  default_harness_id: string;
  default_model: string;
  invocation_mode: string;
  mode: string;
  permission_profile: string;
  stream: boolean;
  workspace_policy: string;
};

const categories = [
  "appearance",
  "runtime",
  "provider",
  "routesModels",
  "harnessDefaults",
  "workspacePermissions",
  "mcp",
  "diagnostics",
] as const;

export function SettingsSurface() {
  const { preferences, setLocale, setTheme } = usePreferences();
  const locale = preferences.locale;
  const queryClient = useQueryClient();
  const settings = useQuery(settingsOptions());
  const [draft, setDraft] = useState<DefaultsDraft | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (settings.data === undefined) return;
    setDraft(toDraft(settings.data));
  }, [settings.data?.revision]);

  const save = useMutation({
    mutationFn: (next: DefaultsDraft) =>
      patchCockpit<SettingsSaveResponse>("/api/settings/defaults", {
        defaults: { ...next, default_model: next.default_model.trim() || null },
        expected_revision: settings.data?.revision,
      }),
    onSuccess: () => {
      setSaved(true);
      void queryClient.invalidateQueries({ queryKey: requestKeys.settings() });
    },
  });
  const runtimeCheck = useMutation({
    mutationFn: () => fetchCockpit<Record<string, unknown>>("/api/health"),
  });
  const modelDiscovery = useMutation({
    mutationFn: () =>
      fetchCockpit<ModelsResponse>(
        withQuery("/api/models", { api_mode: draft?.default_api_mode ?? "v2" }),
      ),
  });

  const modelChoices = useMemo(
    () => modelDiscovery.data?.models ?? settings.data?.routes.models ?? [],
    [modelDiscovery.data?.models, settings.data?.routes.models],
  );

  if (settings.isPending || draft === null) {
    return <div className="settings-loading" aria-busy="true">{message(locale, "loading")}</div>;
  }
  if (settings.isError || settings.data === undefined) {
    return <div className="error-state">{message(locale, "settingsUnavailable")}</div>;
  }
  const data = settings.data;
  const locked = new Set(data.harness_defaults.locked_fields);
  const selectedHarness = data.harness_defaults.harnesses.find(
    (item) => item.id === draft.default_harness_id,
  );

  return (
    <div className="settings-surface">
      <header className="settings-header">
        <div>
          <p className="eyebrow">{message(locale, "backendOwnedSettings")}</p>
          <h1>{message(locale, "settings")}</h1>
          <p>{message(locale, "settingsDescription")}</p>
        </div>
        <button
          className="primary-button"
          disabled={save.isPending}
          onClick={() => { setSaved(false); save.mutate(draft); }}
          type="button"
        >
          {save.isPending ? message(locale, "saving") : message(locale, "saveDefaults")}
        </button>
      </header>

      <div className="settings-layout">
        <nav className="settings-category-rail" aria-label={message(locale, "settingsCategories")}>
          {categories.map((category) => (
            <a href={`#settings-${category}`} key={category}>
              {message(locale, category)}
            </a>
          ))}
        </nav>

        <div className="settings-sections">
          <SettingsSection id="appearance" title={message(locale, "appearance")} description={message(locale, "appearanceHint")}>
            <div className="settings-field-grid">
              <label>{message(locale, "language")}
                <select value={preferences.locale} onChange={(event) => setLocale(event.target.value as LocalePreference)}>
                  <option value="en">English</option><option value="ru">Русский</option>
                </select>
              </label>
              <label>{message(locale, "theme")}
                <select value={preferences.theme} onChange={(event) => setTheme(event.target.value as ThemePreference)}>
                  <option value="light">{message(locale, "light")}</option>
                  <option value="dark">{message(locale, "dark")}</option>
                  <option value="system">{message(locale, "system")}</option>
                </select>
              </label>
            </div>
            <Boundary source="browser" effect="live" />
          </SettingsSection>

          <SettingsSection id="runtime" title={message(locale, "runtime")} description={message(locale, "runtimeHint")}>
            <dl className="settings-facts">
              <Fact label={message(locale, "proxyUrl")} value={data.runtime.proxy_url} mono />
              <Fact label={message(locale, "source")} value={data.runtime.proxy_source} />
              <Fact label={message(locale, "sidecarStartup")} value={data.runtime.auto_start_proxy ? "enabled" : "disabled"} />
              <Fact label={message(locale, "health")} value={runtimeCheck.data ? healthValue(runtimeCheck.data) : data.runtime.proxy_health} />
            </dl>
            <button disabled={runtimeCheck.isPending} onClick={() => runtimeCheck.mutate()} type="button">
              {message(locale, "checkRuntime")}
            </button>
            <Boundary source={data.runtime.proxy_source} effect={data.runtime.change_effect} />
          </SettingsSection>

          <SettingsSection id="provider" title={message(locale, "provider")} description={message(locale, "providerHint")}>
            <dl className="settings-facts">
              <Fact label={message(locale, "configuration")} value={data.provider.configured ? "configured" : "not configured"} />
              <Fact label={message(locale, "source")} value={data.provider.source} />
              <Fact label={message(locale, "credentialValues")} value={message(locale, "backendOnly")} />
            </dl>
            <Boundary source={data.provider.source} effect={data.provider.change_effect} />
          </SettingsSection>

          <SettingsSection id="routesModels" title={message(locale, "routesModels")} description={message(locale, "routesModelsHint")}>
            <div className="settings-field-grid">
              <label>{message(locale, "apiMode")}
                <select disabled={locked.has("default_api_mode")} value={draft.default_api_mode} onChange={(event) => setDraft({ ...draft, default_api_mode: event.target.value })}>
                  <option value="v2">v2</option><option value="v1">v1</option>
                </select>
              </label>
              <label>{message(locale, "model")}
                <input disabled={locked.has("default_model")} list="settings-models" value={draft.default_model} onChange={(event) => setDraft({ ...draft, default_model: event.target.value })} />
                <datalist id="settings-models">{modelChoices.map((model) => <option key={model} value={model} />)}</datalist>
              </label>
            </div>
            <button disabled={modelDiscovery.isPending} onClick={() => modelDiscovery.mutate()} type="button">
              {message(locale, "discoverModels")}
            </button>
            {modelDiscovery.data ? <p className="settings-action-result" role="status">{modelDiscovery.data.ok ? `${modelDiscovery.data.models.length} ${message(locale, "modelsFound")}` : modelDiscovery.data.error}</p> : null}
            <Boundary source={data.harness_defaults.sources.default_model ?? "built_in"} effect={data.routes.change_effect} />
          </SettingsSection>

          <SettingsSection id="harnessDefaults" title={message(locale, "harnessDefaults")} description={message(locale, "harnessDefaultsHint")}>
            <div className="settings-field-grid">
              <label>{message(locale, "harness")}
                <select value={draft.default_harness_id} onChange={(event) => setDraft({ ...draft, default_harness_id: event.target.value })}>
                  {data.harness_defaults.harnesses.map((item) => <option key={item.id} value={item.id}>{item.title} · {item.status}</option>)}
                </select>
              </label>
              <label>{message(locale, "invocation")}
                <select value={draft.invocation_mode} onChange={(event) => setDraft({ ...draft, invocation_mode: event.target.value })}>
                  <option value="headless">{message(locale, "headlessApi")}</option>
                  <option disabled={!selectedHarness?.native_supported} value="native">{message(locale, "nativeCli")}</option>
                </select>
              </label>
              <label>{message(locale, "mode")}
                <select value={draft.mode} onChange={(event) => setDraft({ ...draft, mode: event.target.value })}>
                  <option value="plan">plan</option><option value="act">act</option>
                </select>
              </label>
              <label className="settings-checkbox"><input checked={draft.stream} onChange={(event) => setDraft({ ...draft, stream: event.target.checked })} type="checkbox" />{message(locale, "streamResponse")}</label>
            </div>
            <Boundary source="harness_settings" effect="new_runs" />
          </SettingsSection>

          <SettingsSection id="workspacePermissions" title={message(locale, "workspacePermissions")} description={message(locale, "workspacePermissionsHint")}>
            <div className="settings-field-grid">
              <label>{message(locale, "workspacePolicy")}
                <select value={draft.workspace_policy} onChange={(event) => setDraft({ ...draft, workspace_policy: event.target.value })}>
                  {data.workspace.workspace_policies.map((item) => <option key={item} value={item}>{item}</option>)}
                </select>
              </label>
              <label>{message(locale, "permissionProfile")}
                <select value={draft.permission_profile} onChange={(event) => setDraft({ ...draft, permission_profile: event.target.value })}>
                  {data.workspace.permission_profiles.map((item) => <option key={item} value={item}>{item}</option>)}
                </select>
              </label>
            </div>
            <dl className="settings-facts"><Fact label={message(locale, "project")} value={data.workspace.name} /><Fact label={message(locale, "trusted")} value={String(data.workspace.trusted ?? "not_checked")} /></dl>
            <Boundary source={data.workspace.source} effect="new_runs" />
          </SettingsSection>

          <SettingsSection id="mcp" title={message(locale, "mcp")} description={message(locale, "mcpSettingsHint")}>
            {data.mcp.servers.length === 0 ? <p className="empty-state">{message(locale, "noMcpServers")}</p> : <div className="settings-server-list">{data.mcp.servers.map((server) => <div key={server.id}><div><strong>{server.title}</strong><span>{server.id} · {server.transport}</span></div><span className={`status-label ${server.health === "healthy" ? "success" : ""}`}>{server.enabled ? server.health : "disabled"}</span></div>)}</div>}
            <Boundary source="project_config" effect={data.mcp.change_effect} />
          </SettingsSection>

          <SettingsSection id="diagnostics" title={message(locale, "diagnostics")} description={message(locale, "diagnosticsHint")}>
            <dl className="settings-facts"><Fact label={message(locale, "requestsObserved")} value={String(data.diagnostics.async_data_plane.requests ?? 0)} /><Fact label={message(locale, "contentCapture")} value="off" /></dl>
            <p className="muted-copy">{message(locale, "diagnosticsPrivacy")}</p>
            <SettingsInspectorBoundary />
            <Boundary source="runtime_aggregates" effect="live" />
          </SettingsSection>

          {save.isError ? <p className="mutation-error" role="alert">{save.error.message}</p> : null}
          {saved ? <p className="mutation-success" role="status">{message(locale, "settingsSaved")}</p> : null}
        </div>
      </div>
    </div>
  );
}

function SettingsSection({ children, description, id, title }: { children: React.ReactNode; description: string; id: string; title: string }) {
  return <section className="settings-section" id={`settings-${id}`}><header><h2>{title}</h2><p>{description}</p></header>{children}</section>;
}

function Fact({ label, mono = false, value }: { label: string; mono?: boolean; value: string }) {
  return <div><dt>{label}</dt><dd className={mono ? "mono" : undefined}>{value}</dd></div>;
}

function Boundary({ effect, source }: { effect: string; source: string }) {
  return <div className="settings-boundary"><span>{source}</span><span>{effect.replaceAll("_", " ")}</span></div>;
}

function toDraft(data: SettingsResponse): DefaultsDraft {
  const current = data.harness_defaults;
  return {
    default_api_mode: current.default_api_mode,
    default_harness_id: current.default_harness_id,
    default_model: current.default_model ?? "",
    invocation_mode: current.invocation_mode,
    mode: current.mode,
    permission_profile: current.permission_profile,
    stream: current.stream,
    workspace_policy: current.workspace_policy,
  };
}

function healthValue(value: Record<string, unknown>): string {
  return value.ok === true ? "healthy" : "unavailable";
}

const inspectorKinds: readonly InspectorKind[] = [
  "markdown",
  "diff",
  "terminal",
  "editor",
  "evidence",
];

function SettingsInspectorBoundary() {
  const { preferences } = usePreferences();
  const [kind, setKind] = useState<InspectorKind | null>(null);
  return (
    <details className="operational-inspectors">
      <summary>{message(preferences.locale, "lazyBoundary")}</summary>
      <div className="inspector-actions">
        {inspectorKinds.map((item) => (
          <button key={item} onClick={() => setKind(item)} type="button">
            {message(preferences.locale, item === "evidence" ? "rawEvidence" : item)}
          </button>
        ))}
      </div>
      {kind === null ? null : <LazyInspector kind={kind} locale={preferences.locale} />}
    </details>
  );
}
