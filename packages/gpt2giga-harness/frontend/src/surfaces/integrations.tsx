import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useRouterState, useSearch } from "@tanstack/react-router";
import { useMemo, useState } from "react";

import { mutateCockpit } from "../api";
import { LoadingRows, StatusBadge } from "../components/OperationalSurface";
import { message } from "../messages";
import {
  buildPluginLibrary,
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
  const items = useMemo(
    () => integrationQuery.data
      ? buildPluginLibrary(integrationQuery.data, mcpQuery.data ?? [])
      : [],
    [integrationQuery.data, mcpQuery.data],
  );
  const visibleItems = useMemo(
    () => filterPluginLibrary(items, category, search, connectedOnly, sourceFilter),
    [category, connectedOnly, items, search, sourceFilter],
  );
  const selectedItem = items.find((item) => item.id === selectedId);
  const connectedCount = items.filter((item) => item.connected).length;
  const pending = integrationQuery.isPending;
  const failed = integrationQuery.isError;

  return (
    <div className={`plugin-library ${selectedItem ? "has-selection" : ""}`}>
      <header className="plugin-library-header">
        <h1>{message(locale, "plugins")}</h1>
        <p>{message(locale, "pluginLibraryDescription")}</p>
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
}: {
  category: PluginCategory;
  inventory: IntegrationFlowInventory;
  item: PluginLibraryItem;
}) {
  const { preferences } = usePreferences();
  const locale = preferences.locale;
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
      <section className="plugin-detail-section">
        <h3>{message(locale, "compatibility")}</h3>
        <div className="plugin-targets">
          {displayTargets(item).map((target) => <span key={target}>{target}</span>)}
        </div>
      </section>
      <dl className="plugin-facts">
        <div>
          <dt>{message(locale, "source")}</dt>
          <dd>{sourceLabel(locale, item.source)}</dd>
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
      <PluginConnectionPanel inventory={inventory} item={item} />
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

function descriptionFor(locale: "en" | "ru", item: PluginLibraryItem) {
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
  return message(locale, "installedPackage");
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
