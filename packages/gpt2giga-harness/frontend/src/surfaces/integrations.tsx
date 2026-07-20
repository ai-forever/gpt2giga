import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useRouterState, useSearch } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";

import { fetchCockpit, mutateCockpit } from "../api";
import { LoadingRows, StatusBadge } from "../components/OperationalSurface";
import { message } from "../messages";
import {
  buildPluginLibrary,
  buildRemotePluginLibrary,
  filterPluginLibrary,
  type PluginCategory,
  type PluginItemCategory,
  type PluginLibraryItem,
} from "../plugin-library-model";
import { usePreferences } from "../preferences-context";
import {
  integrationFlowOptions,
  mcpInventoryOptions,
  remainingRequestKeys,
  type IntegrationGroupMutationResponse,
  type IntegrationGroupPreviewResponse,
  type IntegrationFlowInventory,
  type IntegrationFlowMutationResponse,
  type IntegrationFlowPreviewResponse,
  type IntegrationSearchResponse,
  type SkillPreviewResponse,
  type GitInspectionResponse,
} from "../remaining-request-graph";

const categoryPaths = {
  all: "/cockpit-v2/plugins/all",
  mcp: "/cockpit-v2/plugins/mcp",
  plugins: "/cockpit-v2/plugins/plugins",
  skills: "/cockpit-v2/plugins/skills",
} as const;

const categories: readonly PluginCategory[] = ["all", "mcp", "plugins", "skills"];

export function IntegrationsSurface() {
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const category: PluginCategory = pathname.endsWith("/mcp")
    ? "mcp"
    : pathname.endsWith("/plugins")
      ? "plugins"
      : pathname.endsWith("/skills")
        ? "skills"
        : "all";
  const { selected: selectedId } = useSearch({ strict: false });
  const { preferences } = usePreferences();
  const locale = preferences.locale;
  const integrationQuery = useQuery(integrationFlowOptions());
  const mcpQuery = useQuery(mcpInventoryOptions());
  const [search, setSearch] = useState("");
  const [connectedOnly, setConnectedOnly] = useState(false);
  const [sourceFilter, setSourceFilter] = useState<"all" | "built_in" | "external">("all");
  const [harnessFilter, setHarnessFilter] = useState<"all" | "codex" | "claude" | "gemini" | "harness">("all");
  const [remoteSearch, setRemoteSearch] = useState("");
  const [addItem, setAddItem] = useState<PluginLibraryItem | null | true>(null);
  useEffect(() => {
    const timer = window.setTimeout(() => setRemoteSearch(search.trim()), 350);
    return () => window.clearTimeout(timer);
  }, [search]);
  const externalQuery = useQuery({
    queryKey: ["cockpit", "integration-search", remoteSearch, category],
    queryFn: ({ signal }) => {
      const params = new URLSearchParams({ q: remoteSearch, limit: "50" });
      if (category === "skills") params.append("component", "skill");
      else if (category === "mcp") params.append("component", "mcp");
      else {
        params.append("component", "skill");
        params.append("component", "mcp");
      }
      return fetchCockpit<IntegrationSearchResponse>(`/api/integrations/search?${params}`, signal);
    },
    enabled: remoteSearch.length >= 2 && category !== "plugins",
    staleTime: 60_000,
  });
  const items = useMemo(
    () => integrationQuery.data
      ? [
          ...buildPluginLibrary(integrationQuery.data, mcpQuery.data ?? []),
          ...buildRemotePluginLibrary(externalQuery.data),
        ]
      : [],
    [externalQuery.data, integrationQuery.data, mcpQuery.data],
  );
  const visibleItems = useMemo(
    () => filterPluginLibrary(items, category, search, connectedOnly, sourceFilter, harnessFilter),
    [category, connectedOnly, harnessFilter, items, search, sourceFilter],
  );
  const selectedItem = items.find((item) => item.id === selectedId);
  const connectedCount = items.filter((item) => item.connected).length;
  const pending = integrationQuery.isPending;
  const failed = integrationQuery.isError;

  return (
    <div className={`plugin-library ${selectedItem ? "has-selection" : ""}`}>
      <header className="plugin-library-header">
        <div>
          <h1>{message(locale, "plugins")}</h1>
          <p>{message(locale, "pluginLibraryDescription")}</p>
        </div>
        <button className="primary-button plugin-add-button" onClick={() => setAddItem(true)} type="button">
          + {addLabel(locale, category)}
        </button>
      </header>
      <div className="plugin-library-layout">
        <section className="plugin-library-browser">
          <label className="plugin-search">
            <SearchIcon />
            <span className="sr-only">{message(locale, "searchPlugins")}</span>
            <input
              onChange={(event) => setSearch(event.target.value)}
              placeholder={message(locale, "searchPlugins")}
              type="search"
              value={search}
            />
          </label>
          <div className="plugin-library-toolbar">
            <nav className="plugin-category-tabs" aria-label={message(locale, "pluginCategories")}>
              {categories.map((item) => (
                <Link
                  aria-current={category === item ? "page" : undefined}
                  className={category === item ? "active" : ""}
                  key={item}
                  search={{}}
                  to={categoryPaths[item]}
                >
                  {categoryLabel(locale, item)}
                </Link>
              ))}
            </nav>
            <div className="plugin-toolbar-summary">
              <label className="plugin-source-filter">
                <span>{message(locale, "source")}</span>
                <select value={sourceFilter} onChange={(event) => setSourceFilter(event.target.value as typeof sourceFilter)}>
                  <option value="all">{message(locale, "allSources")}</option>
                  <option value="built_in">{message(locale, "builtInCatalog")}</option>
                  <option value="external">{message(locale, "externalSources")}</option>
                </select>
              </label>
              <label className="plugin-source-filter">
                <span>{message(locale, "harness")}</span>
                <select value={harnessFilter} onChange={(event) => setHarnessFilter(event.target.value as typeof harnessFilter)}>
                  <option value="all">{message(locale, "allHarnesses")}</option>
                  <option value="codex">Codex</option>
                  <option value="claude">Claude</option>
                  <option value="gemini">Gemini</option>
                  <option value="harness">Harness</option>
                </select>
              </label>
              <button
                aria-checked={connectedOnly}
                className={`plugin-connected-toggle ${connectedOnly ? "active" : ""}`}
                onClick={() => setConnectedOnly((current) => !current)}
                role="switch"
                type="button"
              >
                <span aria-hidden="true"><i /></span>
                {message(locale, "connectedOnly")}
              </button>
              <span>{connectedCount} {message(locale, "connectedCount")}</span>
            </div>
          </div>
          {externalQuery.data ? (
            <div className="plugin-search-sources" aria-label={message(locale, "searchSources")}>
              <span>{message(locale, "searchSources")}</span>
              {externalQuery.data.sources.map((source) => (
                <span className={`source-status ${source.status}`} key={source.id}>
                  {source.id}: {sourceStatusLabel(locale, source.status)}
                </span>
              ))}
            </div>
          ) : null}
          {pending ? <LoadingRows /> : failed ? (
            <div className="error-state">{message(locale, "boundedDataUnavailable")}</div>
          ) : visibleItems.length === 0 ? (
            <div className="plugin-empty-state">
              <PluginItemIcon category={category === "all" ? "plugins" : category} />
              <strong>{message(locale, "noPluginsFound")}</strong>
              <span>{message(locale, "noPluginsFoundHint")}</span>
            </div>
          ) : (
            <div className="plugin-list">
              {visibleItems.map((item) => (
                <PluginRow
                  category={category}
                  item={item}
                  key={item.id}
                  selected={item.id === selectedId}
                />
              ))}
            </div>
          )}
        </section>
        <aside className="plugin-detail-pane">
          {selectedItem && integrationQuery.data ? (
            <PluginDetails
              category={category}
              inventory={integrationQuery.data}
              item={selectedItem}
              key={selectedItem.id}
              onAdd={() => setAddItem(selectedItem)}
            />
          ) : (
            <div className="plugin-detail-empty">
              <PluginItemIcon category="plugins" />
              <h2>{message(locale, "selectPlugin")}</h2>
              <p>{message(locale, "selectPluginHint")}</p>
            </div>
          )}
        </aside>
      </div>
      {addItem ? (
        <AddIntegrationDrawer
          category={category}
          inventory={integrationQuery.data}
          onClose={() => setAddItem(null)}
          seed={addItem === true ? null : addItem}
        />
      ) : null}
    </div>
  );
}

function PluginRow({
  category,
  item,
  selected,
}: {
  category: PluginCategory;
  item: PluginLibraryItem;
  selected: boolean;
}) {
  const { preferences } = usePreferences();
  const locale = preferences.locale;
  return (
    <Link
      className={`plugin-row ${selected ? "selected" : ""}`}
      data-source-type={item.catalogSourceType ?? item.source}
      search={{ selected: item.id }}
      to={categoryPaths[category]}
    >
      <PluginItemIcon category={item.category} />
      <div className="plugin-row-copy">
        <div>
          <strong>{item.title}</strong>
          <span className="plugin-type-label">{typeLabel(locale, item.category)}</span>
        </div>
        <p>{descriptionFor(locale, item)}</p>
      </div>
      <div className="plugin-targets" aria-label={message(locale, "compatibility")}>
        {displayTargets(item).map((target) => <span key={target}>{target}</span>)}
      </div>
      <span className={`plugin-row-action ${item.connected ? "connected" : ""}`}>
        {item.connected ? <i aria-hidden="true" /> : null}
        {item.connected ? message(locale, "connected") : message(locale, "connect")}
      </span>
    </Link>
  );
}

function PluginDetails({
  category,
  inventory,
  item,
  onAdd,
}: {
  category: PluginCategory;
  inventory: IntegrationFlowInventory;
  item: PluginLibraryItem;
  onAdd: () => void;
}) {
  const { preferences } = usePreferences();
  const locale = preferences.locale;
  const skillPreview = useQuery({
    queryKey: ["cockpit", "skill-preview", item.previewId],
    queryFn: ({ signal }) => fetchCockpit<SkillPreviewResponse>(
      `/api/integrations/skills/preview?preview_id=${encodeURIComponent(item.previewId ?? "")}`,
      signal,
    ),
    enabled: item.category === "skills" && item.previewId !== null,
  });
  return (
    <div className="plugin-detail">
      <Link
        aria-label={message(locale, "closeDetails")}
        className="plugin-detail-close"
        search={{}}
        to={categoryPaths[category]}
      >
        <CloseIcon />
      </Link>
      <div className="plugin-detail-heading">
        <PluginItemIcon category={item.category} />
        <div>
          <h2>{item.title}</h2>
          <span className="plugin-type-label">{typeLabel(locale, item.category)}</span>
        </div>
      </div>
      <p className="plugin-detail-description">{descriptionFor(locale, item)}</p>
      {item.popularity !== null ? (
        <p className="plugin-popularity">{item.popularity.toLocaleString()} {message(locale, "installs")}</p>
      ) : null}
      <section className="plugin-detail-section">
        <h3>{message(locale, "compatibility")}</h3>
        <div className="plugin-targets">
          {displayTargets(item).map((target) => <span key={target}>{target}</span>)}
        </div>
      </section>
      <dl className="plugin-facts">
        <div>
          <dt>{message(locale, "source")}</dt>
          <dd>{item.sourceId ?? sourceLabel(locale, item.source)}</dd>
        </div>
        <div>
          <dt>{message(locale, "version")}</dt>
          <dd>{item.version ?? "—"}</dd>
        </div>
        <div>
          <dt>{message(locale, "connectionStatus")}</dt>
          <dd>{item.connected ? message(locale, "connected") : statusLabel(locale, item.status)}</dd>
        </div>
      </dl>
      {item.category === "skills" && item.previewId ? (
        <section className="plugin-skill-preview">
          <h3>{message(locale, "skillPreview")}</h3>
          {skillPreview.isPending ? <LoadingRows /> : null}
          {skillPreview.data ? <pre>{skillPreview.data.markdown}</pre> : null}
          {skillPreview.isError ? <p className="mutation-error">{skillPreview.error.message}</p> : null}
        </section>
      ) : null}
      {item.source === "remote" ? (
        <div className="plugin-detail-actions">
          <button className="primary-button" disabled={!item.artifactUrl} onClick={onAdd} type="button">
            + {addLabel(locale, item.category)}
          </button>
          {item.detailUrl ? <a href={item.detailUrl} rel="noreferrer" target="_blank">{message(locale, "openSourcePage")}</a> : null}
        </div>
      ) : <PluginConnectionPanel inventory={inventory} item={item} />}
    </div>
  );
}

function PluginConnectionPanel({
  inventory,
  item,
}: {
  inventory: IntegrationFlowInventory;
  item: PluginLibraryItem;
}) {
  const { preferences } = usePreferences();
  const locale = preferences.locale;
  const queryClient = useQueryClient();
  const availableTargets = inventory.targets.filter((target) => item.targetIds.includes(target.id));
  const [targetId, setTargetId] = useState(availableTargets[0]?.id ?? "");
  const [allowNetwork, setAllowNetwork] = useState(false);
  const [nativeConsent, setNativeConsent] = useState(false);
  const canConnectAll = item.category === "skills"
    && ["codex-skill", "claude-skill", "gemini-skill"].every((target) => item.targetIds.includes(target));
  const selectedTarget = availableTargets.find((target) => target.id === targetId) ?? availableTargets[0];
  const selectedScope = selectedTarget?.scopes.includes("managed_home")
    ? "managed_home"
    : selectedTarget?.scopes[0];
  const preview = useMutation({
    mutationFn: () => {
      if (!item.catalogId || !selectedTarget || !selectedScope) {
        throw new Error("This package cannot be connected from the catalog");
      }
      return mutateCockpit<IntegrationFlowPreviewResponse>("/api/integrations/preview", {
        source: "catalog",
        catalog_id: item.catalogId,
        target_id: selectedTarget.id,
        scope: selectedScope,
        configuration: {},
      });
    },
  });
  const apply = useMutation({
    mutationFn: () => {
      if (!preview.data) throw new Error("Preview the connection first");
      return mutateCockpit<IntegrationFlowMutationResponse>(
        `/api/integrations/flows/${encodeURIComponent(preview.data.flow.id)}/apply`,
        {
          plan_id: preview.data.plan.plan_id,
          authority: "cockpit-operator",
          allow_network: allowNetwork,
          native_consent_acknowledged: nativeConsent,
        },
      );
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: remainingRequestKeys.integrationFlows() });
    },
  });
  const groupPreview = useMutation({
    mutationFn: () => {
      if (!item.catalogId) throw new Error("This package cannot be connected from the catalog");
      return mutateCockpit<IntegrationGroupPreviewResponse>("/api/integrations/groups/preview", {
        source: "catalog",
        catalog_id: item.catalogId,
        scope: "managed_home",
        target_mode: "all_supported",
        configuration: {},
      });
    },
  });
  const groupApply = useMutation({
    mutationFn: () => {
      if (!groupPreview.data) throw new Error("Preview all targets first");
      return mutateCockpit<IntegrationGroupMutationResponse>(
        `/api/integrations/groups/${encodeURIComponent(groupPreview.data.group.id)}/apply`,
        {
          plan_id: groupPreview.data.plan.plan_id,
          authority: "cockpit-operator",
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
      if (!item.flow) throw new Error("No connection is available to roll back");
      return mutateCockpit<IntegrationFlowMutationResponse>(
        `/api/integrations/flows/${encodeURIComponent(item.flow.id)}/rollback`,
        {},
      );
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: remainingRequestKeys.integrationFlows() });
    },
  });
  const groupRollback = useMutation({
    mutationFn: () => {
      if (!item.group) throw new Error("No all-target transaction is available");
      return mutateCockpit<IntegrationGroupMutationResponse>(
        `/api/integrations/groups/${encodeURIComponent(item.group.id)}/rollback`,
        {},
      );
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: remainingRequestKeys.integrationFlows() });
    },
  });
  const groupRecover = useMutation({
    mutationFn: () => {
      if (!item.group) throw new Error("No all-target repair is available");
      return mutateCockpit<IntegrationGroupMutationResponse>(
        `/api/integrations/groups/${encodeURIComponent(item.group.id)}/recover`,
        {},
      );
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: remainingRequestKeys.integrationFlows() });
    },
  });
  const probe = useMutation({
    mutationFn: () => item.mcp
      ? mutateCockpit(`/api/tool-servers/${encodeURIComponent(item.mcp.id)}/probe`, {})
      : Promise.reject(new Error("Select an MCP server first")),
  });

  if (item.mcp) {
    return (
      <div className="plugin-detail-actions">
        <button
          className="primary-button"
          disabled={!item.mcp.enabled || probe.isPending}
          onClick={() => probe.mutate()}
          type="button"
        >
          {message(locale, "probeMcp")}
        </button>
        {probe.isSuccess ? <p className="mutation-success" role="status">{message(locale, "operationAccepted")}</p> : null}
        {probe.isError ? <p className="mutation-error" role="alert">{probe.error.message}</p> : null}
      </div>
    );
  }

  if (item.connected && item.group?.status !== "repair_required") {
    return (
      <div className="plugin-detail-actions">
        <div className="plugin-connected-notice"><i aria-hidden="true" />{message(locale, "connected")}</div>
        {item.group ? (
          <div className="plugin-group-state">
            <strong>{message(locale, "allHarnesses")}</strong>
            <span>{item.group.children.filter((child) => child.verification_status !== "not_started").length}/{item.group.children.length}</span>
          </div>
        ) : null}
        {item.group?.rollback_available ? (
          <button disabled={groupRollback.isPending} onClick={() => groupRollback.mutate()} type="button">
            {message(locale, "rollbackAll")}
          </button>
        ) : null}
        {item.flow?.rollback_available ? (
          <button disabled={rollback.isPending} onClick={() => rollback.mutate()} type="button">
            {message(locale, "rollback")}
          </button>
        ) : null}
        {rollback.isError ? <p className="mutation-error" role="alert">{rollback.error.message}</p> : null}
        {groupRollback.isError ? <p className="mutation-error" role="alert">{groupRollback.error.message}</p> : null}
      </div>
    );
  }

  if (item.group?.status === "repair_required") {
    return (
      <div className="plugin-detail-actions">
        <p className="mutation-error" role="alert">{message(locale, "partialInstallNeedsRepair")}</p>
        <ul className="plugin-repair-actions">
          {item.group.repair_actions.map((action) => <li key={action}>{action}</li>)}
        </ul>
        <button disabled={groupRecover.isPending} onClick={() => groupRecover.mutate()} type="button">
          {message(locale, "retrySafeRecovery")}
        </button>
      </div>
    );
  }

  if (!item.catalogId || availableTargets.length === 0) {
    return (
      <div className="plugin-detail-actions">
        <p className="plugin-unavailable-note">{message(locale, "connectionUnavailable")}</p>
        <StatusBadge status={item.status} />
      </div>
    );
  }

  return (
    <div className="plugin-detail-actions">
      <label className="field-control">
        {message(locale, "connectTo")}
        <select
          onChange={(event) => {
            setTargetId(event.target.value);
            preview.reset();
            apply.reset();
          }}
          value={selectedTarget?.id ?? ""}
        >
          {availableTargets.map((target) => (
            <option key={target.id} value={target.id}>{targetLabel(target.id)}</option>
          ))}
        </select>
      </label>
      {!preview.data ? (
        <div className="plugin-connect-choices">
          <button className="primary-button" disabled={preview.isPending} onClick={() => preview.mutate()} type="button">
            {message(locale, "connect")}
          </button>
          {canConnectAll ? (
            <button disabled={groupPreview.isPending} onClick={() => groupPreview.mutate()} type="button">
              {message(locale, "installAllHarnesses")}
            </button>
          ) : null}
        </div>
      ) : (
        <section className="plugin-approval-panel">
          <h3>{message(locale, "beforeConnecting")}</h3>
          <dl className="plugin-facts">
            <div>
              <dt>{message(locale, "permissions")}</dt>
              <dd>{preview.data.plan.permissions.requirements.map((requirement) => requirement.type).join(", ") || message(locale, "noExtraPermissions")}</dd>
            </div>
            <div>
              <dt>{message(locale, "configurationDiff")}</dt>
              <dd>{preview.data.plan.configuration.diff.length || 0}</dd>
            </div>
          </dl>
          {preview.data.plan.permissions.network ? (
            <label className="check-control">
              <input checked={allowNetwork} onChange={(event) => setAllowNetwork(event.target.checked)} type="checkbox" />
              {message(locale, "allowNetwork")}
            </label>
          ) : null}
          {preview.data.plan.permissions.native_consent ? (
            <label className="check-control">
              <input checked={nativeConsent} onChange={(event) => setNativeConsent(event.target.checked)} type="checkbox" />
              {message(locale, "nativeConsent")}
            </label>
          ) : null}
          <button className="primary-button" disabled={apply.isPending} onClick={() => apply.mutate()} type="button">
            {message(locale, "approveAndApply")}
          </button>
          {apply.data ? <p className="mutation-success" role="status">{statusLabel(locale, apply.data.flow.status)}</p> : null}
          {apply.isError ? <p className="mutation-error" role="alert">{apply.error.message}</p> : null}
        </section>
      )}
      {groupPreview.data ? (
        <section className="plugin-approval-panel plugin-group-approval">
          <h3>{message(locale, "allTargetPreview")}</h3>
          <p>{message(locale, "compensatingTransactionNotice")}</p>
          <ol>
            {groupPreview.data.plan.children.map((child) => (
              <li key={child.target_id}>
                <strong>{targetLabel(child.target_id)}</strong>
                <span>{child.configuration_diff.length} {message(locale, "changes")}</span>
              </li>
            ))}
          </ol>
          <button className="primary-button" disabled={groupApply.isPending} onClick={() => groupApply.mutate()} type="button">
            {message(locale, "approveAndInstallAll")}
          </button>
          {groupApply.data ? <p className="mutation-success" role="status">{statusLabel(locale, groupApply.data.group.status)}</p> : null}
          {groupApply.isError ? <p className="mutation-error" role="alert">{groupApply.error.message}</p> : null}
        </section>
      ) : null}
      {groupPreview.isError ? <p className="mutation-error" role="alert">{groupPreview.error.message}</p> : null}
      {preview.isError ? <p className="mutation-error" role="alert">{preview.error.message}</p> : null}
    </div>
  );
}

function AddIntegrationDrawer({
  category,
  inventory,
  onClose,
  seed,
}: {
  category: PluginCategory;
  inventory: IntegrationFlowInventory | undefined;
  onClose: () => void;
  seed: PluginLibraryItem | null;
}) {
  const { preferences } = usePreferences();
  const locale = preferences.locale;
  const queryClient = useQueryClient();
  const initialMode: PluginItemCategory = seed?.category
    ?? (category === "all" ? "skills" : category);
  const [mode, setMode] = useState<PluginItemCategory>(initialMode);
  const [repositoryUrl, setRepositoryUrl] = useState(seed?.artifactUrl ?? "");
  const [ref, setRef] = useState("");
  const [selectedCandidateId, setSelectedCandidateId] = useState("");
  const [catalogId, setCatalogId] = useState("");
  const [targetId, setTargetId] = useState("");
  const [scope, setScope] = useState("managed_home");
  const [packageId, setPackageId] = useState("custom-mcp");
  const [transport, setTransport] = useState("stdio");
  const [command, setCommand] = useState("custom-mcp");
  const [allowNetwork, setAllowNetwork] = useState(false);
  const [nativeConsent, setNativeConsent] = useState(false);
  const inspect = useMutation({
    mutationFn: () => mutateCockpit<GitInspectionResponse>("/api/integrations/git/inspect", {
      repository_url: repositoryUrl,
      ref: ref.trim() || undefined,
    }),
    onSuccess: (data) => setSelectedCandidateId(
      data.candidates.find((item) => item.type === mode.slice(0, -1))?.id
      ?? data.candidates[0]?.id
      ?? "",
    ),
  });
  const candidates = inspect.data?.candidates.filter((item) => (
    mode === "skills" ? item.type === "skill" : mode === "plugins" ? item.type === "plugin" : item.type === "mcp"
  )) ?? [];
  const selectedCandidate = candidates.find((item) => item.id === selectedCandidateId) ?? candidates[0];
  const candidatePreview = useQuery({
    queryKey: ["cockpit", "git-skill-preview", selectedCandidate?.preview_id],
    queryFn: ({ signal }) => fetchCockpit<SkillPreviewResponse>(
      `/api/integrations/skills/preview?preview_id=${encodeURIComponent(selectedCandidate?.preview_id ?? "")}`,
      signal,
    ),
    enabled: selectedCandidate?.preview_id !== null && selectedCandidate?.preview_id !== undefined,
  });
  const importSkill = useMutation({
    mutationFn: () => {
      if (!selectedCandidate) throw new Error("Select a Skill first");
      return mutateCockpit<{ catalog_id: string }>("/api/integrations/git/import-skill", {
        candidate_id: selectedCandidate.id,
      });
    },
    onSuccess: async (data) => {
      setCatalogId(data.catalog_id);
      await queryClient.invalidateQueries({ queryKey: remainingRequestKeys.integrationFlows() });
    },
  });
  const componentHint = mode === "skills" ? "skill" : mode === "mcp" ? "mcp" : "plugin";
  const targets = inventory?.targets.filter((target) => (
    target.component_types.includes(componentHint)
    || (mode === "plugins" && target.component_types.includes("extension"))
  )) ?? [];
  const selectedTarget = targets.find((target) => target.id === targetId) ?? targets[0];
  const selectedScope = selectedTarget?.scopes.includes(scope)
    ? scope
    : selectedTarget?.scopes[0] ?? "managed_home";
  const preview = useMutation({
    mutationFn: () => {
      if (!selectedTarget) throw new Error("No compatible target is available");
      if (mode === "skills" && !catalogId) throw new Error("Import the selected Skill first");
      if (mode === "plugins" && !selectedCandidate?.manifest) throw new Error("Select a plugin manifest first");
      const source = mode === "skills"
        ? "catalog"
        : mode === "mcp"
          ? "raw_descriptor"
          : sourceForManifest(selectedCandidate?.manifest);
      return mutateCockpit<IntegrationFlowPreviewResponse>("/api/integrations/preview", {
        source,
        catalog_id: mode === "skills" ? catalogId : undefined,
        manifest: mode === "plugins" ? selectedCandidate?.manifest : undefined,
        target_id: selectedTarget.id,
        scope: selectedScope,
        package_id: mode === "mcp" ? packageId : undefined,
        configuration: mode === "mcp" ? {
          transport,
          command: transport === "stdio" ? command : undefined,
          url: transport === "stdio" ? undefined : command,
        } : {
          plugin_name: selectedCandidate?.title,
          sparse: selectedCandidate?.relative_dir && selectedCandidate.relative_dir !== "."
            ? [selectedCandidate.relative_dir]
            : [],
        },
      });
    },
  });
  const apply = useMutation({
    mutationFn: () => {
      if (!preview.data) throw new Error("Preview the installation first");
      return mutateCockpit<IntegrationFlowMutationResponse>(
        `/api/integrations/flows/${encodeURIComponent(preview.data.flow.id)}/apply`,
        {
          plan_id: preview.data.plan.plan_id,
          authority: "cockpit-operator",
          allow_network: allowNetwork,
          native_consent_acknowledged: nativeConsent,
        },
      );
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: remainingRequestKeys.integrationFlows() });
    },
  });

  return (
    <div className="plugin-add-backdrop" onMouseDown={onClose} role="presentation">
      <section aria-label={addLabel(locale, mode)} aria-modal="true" className="plugin-add-drawer" onMouseDown={(event) => event.stopPropagation()} role="dialog">
        <header>
          <div><span className="section-kicker">{message(locale, "addIntegration")}</span><h2>+ {addLabel(locale, mode)}</h2></div>
          <button aria-label={message(locale, "closeDetails")} onClick={onClose} type="button"><CloseIcon /></button>
        </header>
        {category === "all" ? (
          <div className="plugin-add-kind">
            {(["skills", "plugins", "mcp"] as const).map((item) => (
              <button className={mode === item ? "selected" : ""} key={item} onClick={() => { setMode(item); preview.reset(); }} type="button">
                {typeLabel(locale, item)}
              </button>
            ))}
          </div>
        ) : null}
        {mode !== "mcp" ? (
          <>
            <label className="field-control">{message(locale, "gitRepository")}
              <input onChange={(event) => setRepositoryUrl(event.target.value)} placeholder="https://github.com/owner/repository/tree/main" value={repositoryUrl} />
            </label>
            <label className="field-control">{message(locale, "gitRefOptional")}
              <input onChange={(event) => setRef(event.target.value)} placeholder="main or an immutable commit" value={ref} />
            </label>
            <button disabled={inspect.isPending || !repositoryUrl.trim()} onClick={() => inspect.mutate()} type="button">{message(locale, "inspectRepository")}</button>
            {inspect.isError ? <p className="mutation-error" role="alert">{inspect.error.message}</p> : null}
            {inspect.data ? <p className="git-commit"><strong>{message(locale, "resolvedCommit")}</strong><code>{inspect.data.commit}</code></p> : null}
            {candidates.length > 0 ? (
              <label className="field-control">{message(locale, "selectCandidate")}
                <select onChange={(event) => { setSelectedCandidateId(event.target.value); setCatalogId(""); preview.reset(); }} value={selectedCandidate?.id ?? ""}>
                  {candidates.map((item) => <option key={item.id} value={item.id}>{item.title} · {item.relative_dir}</option>)}
                </select>
              </label>
            ) : inspect.data ? <p className="plugin-unavailable-note">{message(locale, "noCompatibleCandidates")}</p> : null}
            {candidatePreview.data ? <div className="git-candidate-preview"><strong>{candidatePreview.data.description}</strong><pre>{candidatePreview.data.markdown}</pre></div> : null}
            {mode === "skills" && selectedCandidate ? (
              <button className="primary-button" disabled={importSkill.isPending || Boolean(catalogId)} onClick={() => importSkill.mutate()} type="button">
                {catalogId ? message(locale, "addedToCatalog") : message(locale, "addReviewedSkill")}
              </button>
            ) : null}
            {importSkill.isError ? <p className="mutation-error" role="alert">{importSkill.error.message}</p> : null}
          </>
        ) : (
          <>
            <label className="field-control">{message(locale, "packageId")}<input onChange={(event) => setPackageId(event.target.value)} value={packageId} /></label>
            <label className="field-control">{message(locale, "transport")}<select onChange={(event) => setTransport(event.target.value)} value={transport}><option value="stdio">stdio</option><option value="streamable_http">streamable HTTP</option><option value="sse">SSE</option></select></label>
            <label className="field-control">{transport === "stdio" ? message(locale, "command") : "HTTPS URL"}<input onChange={(event) => setCommand(event.target.value)} value={command} /></label>
          </>
        )}
        <div className="wizard-fields">
          <label className="field-control">{message(locale, "target")}<select onChange={(event) => { setTargetId(event.target.value); preview.reset(); }} value={selectedTarget?.id ?? ""}>{targets.map((target) => <option key={target.id} value={target.id}>{targetLabel(target.id)}</option>)}</select></label>
          <label className="field-control">{message(locale, "scope")}<select onChange={(event) => { setScope(event.target.value); preview.reset(); }} value={selectedScope}>{selectedTarget?.scopes.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
        </div>
        <button disabled={preview.isPending || (mode === "skills" && !catalogId) || (mode === "plugins" && !selectedCandidate?.manifest)} onClick={() => preview.mutate()} type="button">{message(locale, "previewInstall")}</button>
        {preview.isError ? <p className="mutation-error" role="alert">{preview.error.message}</p> : null}
        {preview.data ? (
          <section className="integration-preview">
            <div className="integration-preview-heading"><h2>{preview.data.plan.package.id}</h2><StatusBadge status={preview.data.plan.risk.decision} /></div>
            <dl className="plugin-facts"><div><dt>{message(locale, "target")}</dt><dd>{targetLabel(preview.data.plan.target.id)}</dd></div><div><dt>{message(locale, "configurationDiff")}</dt><dd>{preview.data.plan.configuration.diff.length}</dd></div><div><dt>{message(locale, "permissions")}</dt><dd>{preview.data.plan.permissions.requirements.map((item) => item.type).join(", ") || message(locale, "noExtraPermissions")}</dd></div></dl>
            {preview.data.plan.permissions.network ? <label className="check-control"><input checked={allowNetwork} onChange={(event) => setAllowNetwork(event.target.checked)} type="checkbox" />{message(locale, "allowNetwork")}</label> : null}
            {preview.data.plan.permissions.native_consent ? <label className="check-control"><input checked={nativeConsent} onChange={(event) => setNativeConsent(event.target.checked)} type="checkbox" />{message(locale, "nativeConsent")}</label> : null}
            <button className="primary-button" disabled={apply.isPending} onClick={() => apply.mutate()} type="button">{message(locale, "approveAndApply")}</button>
            {apply.data ? <p className="mutation-success" role="status">{statusLabel(locale, apply.data.flow.status)}</p> : null}
            {apply.isError ? <p className="mutation-error" role="alert">{apply.error.message}</p> : null}
          </section>
        ) : null}
      </section>
    </div>
  );
}

function sourceForManifest(manifest: Record<string, unknown> | null | undefined) {
  const source = manifest?.source_type;
  if (source === "provider_marketplace") return "marketplace";
  if (source === "local") return "local";
  if (source === "package") return "package";
  return "git";
}

function PluginItemIcon({ category }: { category: PluginItemCategory }) {
  if (category === "skills") {
    return <span className="plugin-item-icon skills" aria-hidden="true"><SparklesIcon /></span>;
  }
  if (category === "mcp") {
    return <span className="plugin-item-icon mcp" aria-hidden="true"><CubeIcon /></span>;
  }
  return <span className="plugin-item-icon plugins" aria-hidden="true"><PluginIcon /></span>;
}

function SearchIcon() {
  return <svg aria-hidden="true" viewBox="0 0 24 24"><circle cx="11" cy="11" r="6.5" /><path d="m16 16 4 4" /></svg>;
}

function CloseIcon() {
  return <svg aria-hidden="true" viewBox="0 0 24 24"><path d="m6 6 12 12M18 6 6 18" /></svg>;
}

function SparklesIcon() {
  return <svg viewBox="0 0 24 24"><path d="m12 3 1.3 4.2L17.5 9l-4.2 1.8L12 15l-1.3-4.2L6.5 9l4.2-1.8L12 3Z" /><path d="m18 14 .8 2.2L21 17l-2.2.8L18 20l-.8-2.2L15 17l2.2-.8L18 14Z" /></svg>;
}

function CubeIcon() {
  return <svg viewBox="0 0 24 24"><path d="m12 3 8 4.5v9L12 21l-8-4.5v-9L12 3Z" /><path d="m4 7.5 8 4.5 8-4.5M12 12v9" /></svg>;
}

function PluginIcon() {
  return <svg viewBox="0 0 24 24"><path d="M8.5 4v4.5H4v7h4.5V20h7v-4.5H20v-7h-4.5V4h-7Z" /><path d="M11 4v3M13 17v3M4 12h3M17 12h3" /></svg>;
}

function categoryLabel(locale: "en" | "ru", category: PluginCategory) {
  if (category === "all") return message(locale, "allPlugins");
  if (category === "skills") return message(locale, "skills");
  if (category === "plugins") return message(locale, "plugins");
  return "MCP";
}

function typeLabel(locale: "en" | "ru", category: PluginItemCategory) {
  if (category === "skills") return message(locale, "skill");
  if (category === "plugins") return message(locale, "plugin");
  return "MCP";
}

function addLabel(locale: "en" | "ru", category: PluginCategory | PluginItemCategory) {
  if (category === "skills") return locale === "ru" ? "Добавить Skill" : "Add Skill";
  if (category === "mcp") return locale === "ru" ? "Добавить MCP" : "Add MCP";
  if (category === "plugins") return locale === "ru" ? "Добавить Plugin" : "Add Plugin";
  return message(locale, "addIntegration");
}

function descriptionFor(locale: "en" | "ru", item: PluginLibraryItem) {
  if (item.description) return item.description;
  const descriptions: Record<string, { en: string; ru: string }> = {
    "gpt2giga.builtin.find-skills": {
      en: "Find skills in connected repositories and reviewed catalogs.",
      ru: "Поиск навыков в подключённых репозиториях и проверенных каталогах.",
    },
    "gpt2giga.builtin.skill-creator": {
      en: "Create new skills from instructions and examples.",
      ru: "Создание новых навыков из инструкций и примеров.",
    },
    "gpt2giga.builtin.skill-installer": {
      en: "Install reviewed skills into supported agent homes.",
      ru: "Установка проверенных навыков для поддерживаемых агентов.",
    },
  };
  const known = descriptions[item.packageId];
  if (known) return known[locale];
  if (item.mcp) {
    return locale === "ru"
      ? `MCP-сервер через ${item.mcp.transport}.`
      : `MCP server over ${item.mcp.transport}.`;
  }
  if (item.category === "skills") return message(locale, "skillDescriptionFallback");
  if (item.category === "mcp") return message(locale, "mcpDescriptionFallback");
  return message(locale, "pluginDescriptionFallback");
}

function displayTargets(item: PluginLibraryItem) {
  if (item.mcp) return ["Harness"];
  const targets = new Set(item.targetIds.map(targetLabel));
  return [...targets];
}

function targetLabel(targetId: string) {
  if (targetId.startsWith("codex-")) return "Codex";
  if (targetId.startsWith("claude-")) return "Claude";
  if (targetId.startsWith("gemini-")) return "Gemini";
  if (targetId.startsWith("harness-")) return "Harness";
  return targetId;
}

function sourceLabel(locale: "en" | "ru", source: PluginLibraryItem["source"]) {
  if (source === "catalog") return message(locale, "builtInCatalog");
  if (source === "configured_mcp") return message(locale, "currentConfiguration");
  if (source === "root") return message(locale, "rootSkills");
  if (source === "remote") return message(locale, "externalSources");
  return message(locale, "installedPackage");
}

function sourceStatusLabel(locale: "en" | "ru", status: string) {
  if (status === "ready") return message(locale, "sourceReady");
  if (status === "configuration_required") {
    return message(locale, "sourceConfigurationRequired");
  }
  return message(locale, "sourceUnavailable");
}

function statusLabel(locale: "en" | "ru", status: string) {
  const labels: Record<string, { en: string; ru: string }> = {
    available: { en: "Available", ru: "Доступно" },
    awaiting_approval: { en: "Awaiting approval", ru: "Ожидает подтверждения" },
    failed: { en: "Failed", ru: "Ошибка" },
    handoff_required: { en: "Continue in provider", ru: "Продолжить у провайдера" },
    compensated: { en: "Safely compensated", ru: "Безопасно компенсировано" },
    repair_required: { en: "Repair required", ru: "Требуется восстановление" },
    rolled_back: { en: "Not connected", ru: "Не подключено" },
    verified: { en: "Connected", ru: "Подключено" },
  };
  return labels[status]?.[locale] ?? status;
}
