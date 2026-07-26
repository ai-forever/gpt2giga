import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  type BrowserAccessStatusResponse,
  fetchCockpit,
  mutateCockpit,
  patchCockpit,
  type ModelsResponse,
  type ProviderAccountMutationResponse,
  type ProviderAccountProjection,
  type ProviderCheckResponse,
  type ProviderMutationResponse,
  type ProviderProjection,
  type ProviderSettingsResponse,
  type SettingsResponse,
  type SettingsSaveResponse,
  withQuery,
} from "../api";
import { LazyInspector, type InspectorKind } from "../inspectors/LazyInspector";
import { message } from "../messages";
import type { LocalePreference, ThemePreference } from "../preferences";
import { usePreferences } from "../preferences-context";
import {
  providerAccountsOptions,
  providersOptions,
  requestKeys,
  settingsOptions,
} from "../request-graph";

type DefaultsDraft = {
  default_api_mode: string;
  default_harness_id: string;
  default_model: string;
  default_title_model: string;
  execution_transport: string;
  invocation_mode: string;
  mode: string;
  task_intent: "ask" | "review" | "change";
  authority: "read_only" | "workspace_write";
  permission_profile: string;
  stream: boolean;
  workspace_policy: string;
};

type ProviderDraft = {
  id: string;
  display_name: string;
  protocol: string;
  dialect: string;
  base_url: string;
  route_prefix: string;
  authentication_ownership: string;
  reference_kind: string;
  reference_name: string;
  reference_service: string;
  reference_account: string;
  coding_model: string;
  title_model: string;
  evaluation_model: string;
  fallback_model: string;
  enabled: boolean;
  offline: boolean;
  registry_revision: number | null;
};

const categories = [
  "appearance",
  "localAccess",
  "runtime",
  "providerAccounts",
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
  const browserAccess = useQuery({
    queryKey: ["cockpit", "browser-access"],
    queryFn: ({ signal }) =>
      fetchCockpit<BrowserAccessStatusResponse>("/auth/status", signal),
  });
  const providers = useQuery(providersOptions());
  const providerAccounts = useQuery(providerAccountsOptions());
  const [draft, setDraft] = useState<DefaultsDraft | null>(null);
  const [providerDraft, setProviderDraft] = useState<ProviderDraft | null>(null);
  const [selectedProviderId, setSelectedProviderId] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (settings.data === undefined) return;
    setDraft(toDraft(settings.data));
  }, [settings.data?.revision]);

  useEffect(() => {
    if (providers.data === undefined || providerDraft !== null) return;
    const selected = providers.data.providers[0];
    if (selected !== undefined) {
      setSelectedProviderId(selected.id);
      setProviderDraft(providerToDraft(selected));
      return;
    }
    setProviderDraft(emptyProviderDraft(providers.data.templates[0]));
  }, [providers.data, providerDraft]);

  const save = useMutation({
    mutationFn: (next: DefaultsDraft) =>
      patchCockpit<SettingsSaveResponse>("/api/settings/defaults", {
        defaults: {
          ...next,
          default_model: next.default_model.trim() || null,
          default_title_model: next.default_title_model.trim() || null,
        },
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
  const rotateBrowserAccess = useMutation({
    mutationFn: () =>
      mutateCockpit<{ authenticated: boolean }>("/auth/local/rotate"),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["cockpit", "browser-access"],
      });
    },
  });
  const logoutBrowser = useMutation({
    mutationFn: () =>
      mutateCockpit<{ authenticated: boolean }>("/auth/logout"),
    onSuccess: () => {
      window.location.assign("/local-access");
    },
  });
  const saveProvider = useMutation({
    mutationFn: (next: ProviderDraft) => {
      const body = providerDraftPayload(next);
      return next.registry_revision === null
        ? mutateCockpit<ProviderMutationResponse>("/api/providers", { id: next.id, ...body })
        : patchCockpit<ProviderMutationResponse>(
            `/api/providers/${encodeURIComponent(next.id)}`,
            { expected_revision: next.registry_revision, ...body },
          );
    },
    onSuccess: (response) => {
      setProviderDraft(providerToDraft(response.provider));
      setSelectedProviderId(response.provider.id);
      void queryClient.invalidateQueries({ queryKey: requestKeys.providers() });
      void queryClient.invalidateQueries({ queryKey: requestKeys.settings() });
    },
  });
  const providerTest = useMutation({
    mutationFn: (providerId: string) =>
      mutateCockpit<ProviderCheckResponse>(
        `/api/providers/${encodeURIComponent(providerId)}/test`,
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: requestKeys.providers() });
    },
  });
  const providerDiscovery = useMutation({
    mutationFn: (providerId: string) =>
      mutateCockpit<ProviderCheckResponse>(
        `/api/providers/${encodeURIComponent(providerId)}/discover`,
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: requestKeys.providers() });
    },
  });
  const providerAccountAction = useMutation({
    mutationFn: ({
      providerId,
      action,
    }: {
      providerId: string;
      action: "cancel" | "login" | "logout" | "refresh";
    }) =>
      mutateCockpit<ProviderAccountMutationResponse>(
        `/api/provider-accounts/${encodeURIComponent(providerId)}/${action}`,
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: requestKeys.providerAccounts(),
      });
    },
  });
  const modelDiscovery = useMutation({
    mutationFn: () =>
      fetchCockpit<ModelsResponse>(
        withQuery("/api/models", { api_mode: draft?.default_api_mode ?? "v2" }),
      ),
  });

  const modelChoices = useMemo(() => Array.from(new Set([
    draft?.default_model,
    draft?.default_title_model,
    ...(modelDiscovery.data?.models ?? settings.data?.routes.models ?? []),
  ].filter((model): model is string => Boolean(model)))), [
    draft?.default_model,
    draft?.default_title_model,
    modelDiscovery.data?.models,
    settings.data?.routes.models,
  ]);

  if (
    settings.isPending ||
    browserAccess.isPending ||
    providers.isPending ||
    providerAccounts.isPending ||
    draft === null ||
    providerDraft === null
  ) {
    return <div className="settings-loading" aria-busy="true">{message(locale, "loading")}</div>;
  }
  if (
    settings.isError ||
    browserAccess.isError ||
    providers.isError ||
    providerAccounts.isError ||
    settings.data === undefined ||
    browserAccess.data === undefined ||
    providers.data === undefined ||
    providerAccounts.data === undefined
  ) {
    return <div className="error-state">{message(locale, "settingsUnavailable")}</div>;
  }
  const data = settings.data;
  const providerData = providers.data;
  const selectedProvider = providerData.providers.find((item) => item.id === selectedProviderId);
  const providerErrors = providerFieldErrors(saveProvider.error);
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

          <SettingsSection
            id="localAccess"
            title={message(locale, "localAccess")}
            description={message(locale, "localAccessHint")}
          >
            <dl className="settings-facts">
              <Fact
                label={message(locale, "accessMode")}
                value={browserAccess.data.local ? message(locale, "loopbackLocal") : message(locale, "remoteDeployment")}
              />
              <Fact
                label={message(locale, "browserSession")}
                value={browserAccess.data.authenticated ? message(locale, "active") : message(locale, "expired")}
              />
              <Fact
                label={message(locale, "expiry")}
                value={browserAccess.data.expires_at ?? message(locale, "noExpiry")}
                mono
              />
            </dl>
            <p className="muted-copy">{browserAccess.data.recovery}</p>
            <div className="provider-actions">
              <button
                disabled={!browserAccess.data.local || rotateBrowserAccess.isPending}
                onClick={() => rotateBrowserAccess.mutate()}
                type="button"
              >
                {message(locale, "rotateBrowserSession")}
              </button>
              <button
                className="danger-button"
                disabled={logoutBrowser.isPending}
                onClick={() => logoutBrowser.mutate()}
                type="button"
              >
                {message(locale, "logoutBrowser")}
              </button>
            </div>
            {rotateBrowserAccess.isSuccess ? (
              <p className="mutation-success" role="status">
                {message(locale, "browserSessionRotated")}
              </p>
            ) : null}
            {rotateBrowserAccess.isError || logoutBrowser.isError ? (
              <p className="mutation-error" role="alert">
                {message(locale, "browserAccessActionFailed")}
              </p>
            ) : null}
            <Boundary source="os_local_private_store" effect="current_browser" />
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

          <SettingsSection id="providerAccounts" title={message(locale, "providerAccounts")} description={message(locale, "providerAccountsHint")}>
            <div className="provider-account-grid">
              {providerAccounts.data.accounts.map((account) => (
                <ProviderAccountCard
                  account={account}
                  actionPending={
                    providerAccountAction.isPending &&
                    providerAccountAction.variables?.providerId === account.provider_id
                  }
                  key={account.provider_id}
                  locale={locale}
                  onAction={(action) =>
                    providerAccountAction.mutate({
                      providerId: account.provider_id,
                      action,
                    })}
                />
              ))}
            </div>
            {providerAccountAction.isError ? (
              <p className="mutation-error" role="alert">{message(locale, "loginActionFailed")}</p>
            ) : null}
            <Boundary source="provider_owned_cli" effect="isolated_home_only" />
          </SettingsSection>

          <SettingsSection id="provider" title={message(locale, "provider")} description={message(locale, "providerHint")}>
            <div className="provider-toolbar">
              <select
                aria-label={message(locale, "providerTemplate")}
                onChange={(event) => {
                  const template = providerData.templates.find((item) => item.id === event.target.value);
                  if (template !== undefined) setProviderDraft(emptyProviderDraft(template));
                  setSelectedProviderId(null);
                }}
                value=""
              >
                <option value="">{message(locale, "chooseProviderTemplate")}</option>
                {providerData.templates.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}
              </select>
              <button
                onClick={() => {
                  setSelectedProviderId(null);
                  setProviderDraft(emptyProviderDraft(providerData.templates[0]));
                }}
                type="button"
              >
                {message(locale, "addProvider")}
              </button>
            </div>
            {providerData.providers.length === 0 ? (
              <p className="empty-state">{message(locale, "noProviders")}</p>
            ) : (
              <div className="provider-list" role="list">
                {providerData.providers.map((item) => (
                  <button
                    className={selectedProviderId === item.id ? "selected" : ""}
                    key={item.id}
                    onClick={() => {
                      setSelectedProviderId(item.id);
                      setProviderDraft(providerToDraft(item));
                    }}
                    role="listitem"
                    type="button"
                  >
                    <span><strong>{item.display_name}</strong><small>{item.protocol} · {item.dialect}</small></span>
                    <span className={`status-label ${item.health?.status === "ready" ? "success" : ""}`}>
                      {!item.enabled ? "disabled" : item.health?.status ?? "not checked"}
                    </span>
                  </button>
                ))}
              </div>
            )}
            <div className="settings-field-grid provider-form">
              <ProviderField label={message(locale, "providerId")} error={providerErrors.provider_id}>
                <input disabled={providerDraft.registry_revision !== null} value={providerDraft.id} onChange={(event) => setProviderDraft({ ...providerDraft, id: event.target.value })} />
              </ProviderField>
              <ProviderField label={message(locale, "providerName")} error={providerErrors.display_name}>
                <input value={providerDraft.display_name} onChange={(event) => setProviderDraft({ ...providerDraft, display_name: event.target.value })} />
              </ProviderField>
              <ProviderField label={message(locale, "protocol")} error={providerErrors.protocol}>
                <select value={providerDraft.protocol} onChange={(event) => {
                  const protocol = event.target.value;
                  setProviderDraft({ ...providerDraft, protocol, dialect: dialectsFor(protocol)[0] ?? "" });
                }}>
                  <option value="openai_compatible">OpenAI compatible</option>
                  <option value="anthropic_compatible">Anthropic compatible</option>
                  <option value="gemini_compatible">Gemini compatible</option>
                </select>
              </ProviderField>
              <ProviderField label={message(locale, "dialect")} error={providerErrors.dialect}>
                <select value={providerDraft.dialect} onChange={(event) => setProviderDraft({ ...providerDraft, dialect: event.target.value })}>
                  {dialectsFor(providerDraft.protocol).map((item) => <option key={item} value={item}>{item}</option>)}
                </select>
              </ProviderField>
              <ProviderField label={message(locale, "baseUrl")} error={providerErrors.base_url ?? providerErrors.provider}>
                <input value={providerDraft.base_url} onChange={(event) => setProviderDraft({ ...providerDraft, base_url: event.target.value })} />
              </ProviderField>
              <ProviderField label={message(locale, "routePrefix")} error={providerErrors.route_prefix}>
                <input placeholder="/v1" value={providerDraft.route_prefix} onChange={(event) => setProviderDraft({ ...providerDraft, route_prefix: event.target.value })} />
              </ProviderField>
              <ProviderField label={message(locale, "authentication")} error={providerErrors["authentication.ownership"] ?? providerErrors.authentication}>
                <select value={providerDraft.authentication_ownership} onChange={(event) => setProviderDraft({ ...providerDraft, authentication_ownership: event.target.value })}>
                  <option value="secret_reference">Secret reference</option>
                  <option value="provider_native">Provider native</option>
                  <option value="none">None</option>
                </select>
              </ProviderField>
              {providerDraft.authentication_ownership === "secret_reference" ? <>
                <ProviderField label={message(locale, "secretReferenceKind")} error={providerErrors["authentication.reference_kind"]}>
                  <select value={providerDraft.reference_kind} onChange={(event) => setProviderDraft({ ...providerDraft, reference_kind: event.target.value })}>
                    <option value="environment">Environment</option><option value="keychain">Keychain</option>
                  </select>
                </ProviderField>
                <ProviderField label={message(locale, "secretReferenceName")} error={providerErrors["authentication.reference_name"]}>
                  <input value={providerDraft.reference_name} onChange={(event) => setProviderDraft({ ...providerDraft, reference_name: event.target.value })} />
                </ProviderField>
                {providerDraft.reference_kind === "keychain" ? <>
                  <ProviderField label={message(locale, "keychainService")} error={providerErrors["authentication.reference_name"]}>
                    <input value={providerDraft.reference_service} onChange={(event) => setProviderDraft({ ...providerDraft, reference_service: event.target.value })} />
                  </ProviderField>
                  <ProviderField label={message(locale, "keychainAccount")} error={providerErrors["authentication.reference_name"]}>
                    <input value={providerDraft.reference_account} onChange={(event) => setProviderDraft({ ...providerDraft, reference_account: event.target.value })} />
                  </ProviderField>
                </> : null}
              </> : null}
              <label className="settings-checkbox"><input checked={providerDraft.enabled} onChange={(event) => setProviderDraft({ ...providerDraft, enabled: event.target.checked })} type="checkbox" />{message(locale, "providerEnabled")}</label>
              <label className="settings-checkbox"><input checked={providerDraft.offline} onChange={(event) => setProviderDraft({ ...providerDraft, offline: event.target.checked })} type="checkbox" />{message(locale, "offlineMode")}</label>
            </div>
            <p className="muted-copy">{selectedProvider?.authentication.explanation ?? message(locale, "referenceOnlyAuth")}</p>
            <div className="provider-actions">
              <button disabled={saveProvider.isPending} onClick={() => saveProvider.mutate(providerDraft)} type="button">
                {saveProvider.isPending ? message(locale, "saving") : message(locale, "saveProvider")}
              </button>
              <button disabled={providerDraft.registry_revision === null || providerTest.isPending} onClick={() => providerTest.mutate(providerDraft.id)} type="button">
                {message(locale, "testConnection")}
              </button>
            </div>
            {providerTest.data ? <p className="settings-action-result" role="status">
              {providerTest.data.health.status}
              {providerTest.data.health.failure_kind ? ` · ${providerTest.data.health.failure_kind}: ${providerTest.data.health.reason_code}` : ""}
            </p> : null}
            {selectedProvider ? <>
              <dl className="settings-facts provider-evidence">
                <Fact label={message(locale, "source")} value={selectedProvider.source} />
                <Fact label={message(locale, "health")} value={providerTest.data?.health.status ?? selectedProvider.health?.status ?? "not checked"} />
                <Fact label={message(locale, "credentialValues")} value={message(locale, "backendOnly")} />
                <Fact label={message(locale, "compatibility")} value={`${selectedProvider.compatibility.length} reviewed`} />
              </dl>
              <p className="muted-copy">{selectedProvider.compatibility_explanation}</p>
              <Boundary source={selectedProvider.source} effect={selectedProvider.effects.managed_homes ?? "restart_required"} />
            </> : <Boundary source="user_registry" effect="new_session_required" />}
            {saveProvider.isError ? <p className="mutation-error" role="alert">{message(locale, "providerValidationFailed")}</p> : null}
            {saveProvider.isSuccess ? <p className="mutation-success" role="status">{message(locale, "providerSaved")}</p> : null}
          </SettingsSection>

          <SettingsSection id="routesModels" title={message(locale, "routesModels")} description={message(locale, "routesModelsHint")}>
            <h3 className="settings-subheading">{message(locale, "providerPurposeDefaults")}</h3>
            <div className="settings-field-grid">
              <ProviderField label={message(locale, "codingModel")} error={providerErrors["default_models.coding"]}>
                <input value={providerDraft.coding_model} onChange={(event) => setProviderDraft({ ...providerDraft, coding_model: event.target.value })} />
              </ProviderField>
              <ProviderField label={message(locale, "titleModel")} error={providerErrors["default_models.title"]}>
                <input value={providerDraft.title_model} onChange={(event) => setProviderDraft({ ...providerDraft, title_model: event.target.value })} />
              </ProviderField>
              <ProviderField label={message(locale, "evaluationModel")} error={providerErrors["default_models.evaluation"]}>
                <input value={providerDraft.evaluation_model} onChange={(event) => setProviderDraft({ ...providerDraft, evaluation_model: event.target.value })} />
              </ProviderField>
              <ProviderField label={message(locale, "fallbackModel")} error={providerErrors["default_models.fallback"]}>
                <input value={providerDraft.fallback_model} onChange={(event) => setProviderDraft({ ...providerDraft, fallback_model: event.target.value })} />
              </ProviderField>
            </div>
            <div className="provider-actions">
              <button disabled={saveProvider.isPending} onClick={() => saveProvider.mutate(providerDraft)} type="button">{message(locale, "saveRoutes")}</button>
              <button disabled={providerDraft.registry_revision === null || providerDiscovery.isPending} onClick={() => providerDiscovery.mutate(providerDraft.id)} type="button">{message(locale, "discoverModels")}</button>
            </div>
            {providerDiscovery.data ? <p className="settings-action-result" role="status">
              {providerDiscovery.data.health.discovery_status} · {providerDiscovery.data.health.models.length} {message(locale, "modelsFound")}
            </p> : null}
            {selectedProvider?.routes.length ? <div className="provider-route-list">
              {selectedProvider.routes.map((route) => <div key={route.id}><strong>{route.purpose}</strong><span>{route.model}</span><small>{route.id}</small></div>)}
            </div> : <p className="empty-state">{message(locale, "noProviderRoutes")}</p>}
            <Boundary source={selectedProvider?.source ?? "user_registry"} effect="fork_or_new_session_required" />
            <h3 className="settings-subheading">{message(locale, "workbenchFallbackDefaults")}</h3>
            <div className="settings-field-grid">
              <label>{message(locale, "apiMode")}
                <select disabled={locked.has("default_api_mode")} value={draft.default_api_mode} onChange={(event) => setDraft({ ...draft, default_api_mode: event.target.value })}>
                  <option value="v2">v2</option><option value="v1">v1</option>
                </select>
              </label>
              <label>{message(locale, "chatModel")}
                <select disabled={locked.has("default_model")} value={draft.default_model} onChange={(event) => setDraft({ ...draft, default_model: event.target.value })}>
                  <option value="">{message(locale, "noDefaultModel")}</option>
                  {modelChoices.map((model) => <option key={model} value={model}>{model}</option>)}
                </select>
              </label>
              <label>{message(locale, "titleModel")}
                <select value={draft.default_title_model} onChange={(event) => setDraft({ ...draft, default_title_model: event.target.value })}>
                  <option value="">{message(locale, "useChatModel")}</option>
                  {modelChoices.map((model) => <option key={model} value={model}>{model}</option>)}
                </select>
              </label>
            </div>
            <button disabled={modelDiscovery.isPending} onClick={() => modelDiscovery.mutate()} type="button">
              {message(locale, "discoverLegacyModels")}
            </button>
            {modelDiscovery.data ? <p className="settings-action-result" role="status">{modelDiscovery.data.ok ? `${modelDiscovery.data.models.length} ${message(locale, "modelsFound")}` : modelDiscovery.data.error}</p> : null}
            <Boundary source={data.harness_defaults.sources.default_model ?? "built_in"} effect={data.routes.change_effect} />
          </SettingsSection>

          <SettingsSection id="harnessDefaults" title={message(locale, "harnessDefaults")} description={message(locale, "harnessDefaultsHint")}>
            <div className="settings-field-grid">
              <label>{message(locale, "harness")}
                <select value={draft.default_harness_id} onChange={(event) => {
                  const harness = data.harness_defaults.harnesses.find((item) => item.id === event.target.value);
                  const transport = harness?.workbench_transport.default ?? "one_shot";
                  setDraft({
                    ...draft,
                    default_harness_id: event.target.value,
                    execution_transport: transport,
                    invocation_mode: transport === "native_terminal" ? "native" : "headless",
                  });
                }}>
                  {data.harness_defaults.harnesses.map((item) => <option key={item.id} value={item.id}>{item.title} · {item.status}</option>)}
                </select>
              </label>
              <label>{message(locale, "executionTransport")}
                <select value={draft.execution_transport} onChange={(event) => {
                  const transport = event.target.value;
                  setDraft({
                    ...draft,
                    execution_transport: transport,
                    invocation_mode: transport === "native_terminal" ? "native" : "headless",
                  });
                }}>
                  {selectedHarness?.workbench_transport.options.map((option) => (
                    <option key={option.id} value={option.id}>
                      {message(locale, option.id === "native_structured" ? "nativeStructured" : option.id === "native_terminal" ? "nativeTerminal" : "oneShot")}
                      {option.status === "blocked" ? ` · ${message(locale, "blocked")}` : ""}
                    </option>
                  ))}
                </select>
              </label>
              <label>{message(locale, "intent")}
                <select value={draft.task_intent} onChange={(event) => setDraft({
                  ...draft,
                  task_intent: event.target.value as DefaultsDraft["task_intent"],
                })}>
                  <option value="ask">{message(locale, "ask")}</option>
                  <option value="review">{message(locale, "review")}</option>
                  <option value="change">{message(locale, "change")}</option>
                </select>
              </label>
              <label>{message(locale, "authority")}
                <select value={draft.authority} onChange={(event) => setDraft({
                  ...draft,
                  authority: event.target.value as DefaultsDraft["authority"],
                })}>
                  <option value="read_only">{message(locale, "readOnly")}</option>
                  <option value="workspace_write">{message(locale, "workspaceWrite")}</option>
                </select>
              </label>
              {data.harness_defaults.compatibility.mode === null ? null : (
                <div className="runtime-owned-setting" role="status">
                  <strong>{message(locale, "legacyModeWarningTitle")}</strong>
                  <span>{message(locale, "legacyModeWarning")}</span>
                </div>
              )}
              <div className="runtime-owned-setting">
                <strong>{message(locale, "streamRuntimeOwnedTitle")}</strong>
                <span>{message(locale, "streamRuntimeOwned")}</span>
              </div>
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

function ProviderField({ children, error, label }: { children: React.ReactNode; error?: string; label: string }) {
  return <label>{label}{children}{error ? <span className="settings-field-error">{error}</span> : null}</label>;
}

function ProviderAccountCard({
  account,
  actionPending,
  locale,
  onAction,
}: {
  account: ProviderAccountProjection;
  actionPending: boolean;
  locale: LocalePreference;
  onAction: (action: "cancel" | "login" | "logout" | "refresh") => void;
}) {
  const pending = account.status === "pending";
  return (
    <article className="provider-account-card">
      <header>
        <div>
          <strong>{account.display_name}</strong>
          <small>{account.provider_id}</small>
        </div>
        <span className={`status-label ${account.status === "ready" ? "success" : ""}`}>
          {account.status}
        </span>
      </header>
      <dl className="settings-facts">
        <Fact label={message(locale, "source")} value={account.source} mono />
        <Fact
          label={message(locale, "detectedVersion")}
          value={account.detected_cli_version ?? message(locale, "cliNotDetected")}
        />
        <Fact
          label={message(locale, "authentication")}
          value={account.authentication_method ?? message(locale, "providerOwnedCredentials")}
        />
        <Fact
          label={message(locale, "expiry")}
          value={account.expires_at ?? message(locale, "noExpiry")}
        />
      </dl>
      <p className="provider-account-recovery">
        <strong>{message(locale, "accountRecovery")}</strong>
        <span>{account.recovery[0] ?? account.reason_code}</span>
      </p>
      {pending ? (
        <p className="settings-action-result" role="status">
          {message(locale, "loginPendingHint")}
        </p>
      ) : null}
      <div className="provider-actions">
        <button
          disabled={!account.actions.status || actionPending || pending}
          onClick={() => onAction("refresh")}
          type="button"
        >
          {message(locale, "refreshStatus")}
        </button>
        {pending ? (
          <button
            disabled={!account.actions.cancel || actionPending}
            onClick={() => onAction("cancel")}
            type="button"
          >
            {message(locale, "cancelLogin")}
          </button>
        ) : (
          <button
            disabled={!account.actions.start || actionPending}
            onClick={() => onAction("login")}
            type="button"
          >
            {message(locale, "startLogin")}
          </button>
        )}
        <button
          disabled={!account.actions.logout || actionPending || pending}
          onClick={() => onAction("logout")}
          type="button"
        >
          {message(locale, "logout")}
        </button>
      </div>
    </article>
  );
}

function emptyProviderDraft(template: ProviderSettingsResponse["templates"][number] | undefined): ProviderDraft {
  return {
    id: "",
    display_name: template?.title ?? "",
    protocol: template?.protocol ?? "openai_compatible",
    dialect: template?.dialect ?? "openai-responses-v1",
    base_url: template?.base_url ?? "",
    route_prefix: template?.route_prefix ?? "",
    authentication_ownership: template?.authentication ?? "secret_reference",
    reference_kind: "environment",
    reference_name: template?.secret_reference_name ?? "",
    reference_service: "",
    reference_account: "",
    coding_model: "",
    title_model: "",
    evaluation_model: "",
    fallback_model: "",
    enabled: true,
    offline: false,
    registry_revision: null,
  };
}

function providerToDraft(provider: ProviderProjection): ProviderDraft {
  return {
    id: provider.id,
    display_name: provider.display_name,
    protocol: provider.protocol,
    dialect: provider.dialect,
    base_url: provider.base_url,
    route_prefix: provider.route_prefix ?? "",
    authentication_ownership: provider.authentication.ownership,
    reference_kind: provider.authentication.reference_kind ?? "environment",
    reference_name: provider.authentication.reference_name ?? "",
    reference_service: provider.authentication.service ?? "",
    reference_account: provider.authentication.account ?? "",
    coding_model: provider.default_models.coding ?? "",
    title_model: provider.default_models.title ?? "",
    evaluation_model: provider.default_models.evaluation ?? "",
    fallback_model: provider.default_models.fallback ?? "",
    enabled: provider.enabled,
    offline: provider.offline,
    registry_revision: provider.registry_revision,
  };
}

function providerDraftPayload(draft: ProviderDraft): Readonly<Record<string, unknown>> {
  const authentication = draft.authentication_ownership === "secret_reference"
    ? {
        ownership: draft.authentication_ownership,
        reference_kind: draft.reference_kind,
        reference_name: draft.reference_name.trim(),
        ...(draft.reference_kind === "keychain" ? {
          service: draft.reference_service.trim() || null,
          account: draft.reference_account.trim() || null,
        } : {}),
      }
    : { ownership: draft.authentication_ownership };
  const defaultModels = Object.fromEntries(Object.entries({
    coding: draft.coding_model,
    title: draft.title_model,
    evaluation: draft.evaluation_model,
    fallback: draft.fallback_model,
  }).flatMap(([purpose, model]) => model.trim() ? [[purpose, model.trim()]] : []));
  return {
    display_name: draft.display_name.trim(),
    protocol: draft.protocol,
    dialect: draft.dialect,
    base_url: draft.base_url.trim(),
    route_prefix: draft.route_prefix.trim() || null,
    authentication,
    default_models: defaultModels,
    enabled: draft.enabled,
    offline: draft.offline,
  };
}

function dialectsFor(protocol: string): string[] {
  if (protocol === "anthropic_compatible") {
    return [
      "anthropic-messages-v1",
      "anthropic-bedrock-v1",
      "anthropic-vertex-v1",
      "anthropic-foundry-v1",
    ];
  }
  if (protocol === "gemini_compatible") {
    return ["gemini-generate-content-v1beta", "gemini-vertex-v1"];
  }
  return ["openai-responses-v1", "openai-chat-completions-v1"];
}

function providerFieldErrors(error: Error | null): Record<string, string> {
  if (error === null) return {};
  try {
    const payload = JSON.parse(error.message) as {
      detail?: { field_errors?: Record<string, string> };
    };
    return payload.detail?.field_errors ?? {};
  } catch {
    return {};
  }
}

function toDraft(data: SettingsResponse): DefaultsDraft {
  const current = data.harness_defaults;
  return {
    default_api_mode: current.default_api_mode,
    default_harness_id: current.default_harness_id,
    default_model: current.default_model ?? "",
    default_title_model: current.default_title_model ?? "",
    execution_transport: current.execution_transport,
    invocation_mode: current.invocation_mode,
    mode: current.mode,
    task_intent: current.task_intent,
    authority: current.authority,
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
