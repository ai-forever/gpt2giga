import type { AdminApp } from "../app.js";
import { CANONICAL_DOC_LINKS, OPERATOR_GUIDE_LINKS } from "../docs-links.js";
import { pathForPage } from "../routes.js";
import {
  banner,
  card,
  kpi,
  pill,
  renderDefinitionList,
  renderGuideLinks,
  renderPageFrame,
  renderPageSection,
  renderStatLines,
  renderTable,
} from "../templates.js";
import type { RuntimePayload, SetupPayload } from "../types.js";
import {
  asArray,
  asRecord,
  describeGigachatAuth,
  describePersistenceStatus,
  escapeHtml,
  formatNumber,
  formatTimestamp,
} from "../utils.js";

type UsageRow = Record<string, unknown>;
type ErrorEvent = Record<string, unknown>;

const MAX_SUMMARY_ROWS = 5;

export async function renderOverview(app: AdminApp, token: number): Promise<void> {
  const [runtime, setup, usageProviders, errors] = await Promise.all([
    app.api.json<RuntimePayload>("/admin/api/runtime"),
    app.api.json<SetupPayload>("/admin/api/setup"),
    app.api.json<Record<string, unknown>>("/admin/api/usage/providers"),
    app.api.json<Record<string, unknown>>("/admin/api/errors/recent?limit=5"),
  ]);

  if (!app.isCurrentRender(token)) {
    return;
  }

  const runtimeRecord = asRecord(runtime);
  const summary = asRecord(usageProviders.summary);
  const providerEntries = asArray<UsageRow>(usageProviders.entries).slice(0, MAX_SUMMARY_ROWS);
  const recentErrors = asArray<ErrorEvent>(errors.events)
    .slice(-MAX_SUMMARY_ROWS)
    .reverse();
  const enabledProviders = asArray<string>(runtimeRecord.enabled_providers);
  const requestCount = Number(summary.request_count ?? 0);
  const errorCount = Number(summary.error_count ?? 0);
  const totalTokens = Number(summary.total_tokens ?? 0);
  const topProvider = providerEntries[0] ?? null;
  const persistence = describePersistenceStatus(setup);
  const gigachatAuth = describeGigachatAuth(setup);
  const gatewayAuthReady = Boolean(runtimeRecord.auth_required);
  const docsEnabled = Boolean(runtimeRecord.docs_enabled);
  const nextSurface = describeNextSurface(setup, errorCount, requestCount);

  app.setHeroActions(
    setup.setup_complete
      ? `
          <a class="button" href="/admin/playground">Try playground</a>
          <a class="button button--secondary" href="/admin/logs">Open logs</a>
          <a class="button button--secondary" href="/admin/settings">Open settings</a>
        `
      : `
          <a class="button" href="/admin/setup">Open setup wizard</a>
          <a class="button button--secondary" href="/admin/keys">Open API keys</a>
          <a class="button button--secondary" href="/admin/settings">Open settings</a>
        `,
  );

  app.setContent(
    renderPageFrame({
      toolbar: `
        <div class="toolbar">
          ${
            setup.setup_complete
              ? `
                  <a class="button" href="${escapeHtml(pathForPage("playground"))}">Playground</a>
                  <a class="button button--secondary" href="${escapeHtml(pathForPage("traffic"))}">Traffic</a>
                  <a class="button button--secondary" href="${escapeHtml(pathForPage("logs"))}">Logs</a>
                  <a class="button button--secondary" href="${escapeHtml(pathForPage("settings"))}">Settings</a>
                `
              : `
                  <a class="button" href="${escapeHtml(pathForPage("setup"))}">Setup</a>
                  <a class="button button--secondary" href="${escapeHtml(pathForPage("keys"))}">API Keys</a>
                  <a class="button button--secondary" href="${escapeHtml(pathForPage("settings"))}">Settings</a>
                `
          }
        </div>
        <div class="pill-row">
          ${pill(persistence.pillLabel, persistence.tone)}
          ${pill(gigachatAuth.pillLabel, gigachatAuth.tone)}
          ${pill(`Gateway auth ${gatewayAuthReady ? "required" : "open"}`, gatewayAuthReady ? "good" : "warn")}
          ${pill(`Docs ${docsEnabled ? "exposed" : "disabled"}`, docsEnabled ? "warn" : "good")}
          ${pill(`Telemetry ${runtime.telemetry_enabled ? "enabled" : "disabled"}`)}
        </div>
      `,
      stats: [
        kpi("Setup", setup.setup_complete ? "complete" : "needs action"),
        kpi("Requests", formatNumber(requestCount)),
        kpi("Error rate", formatPercent(errorCount, requestCount)),
        kpi("Providers", formatNumber(enabledProviders.length)),
      ],
      sections: [
        renderPageSection({
          eyebrow: "Dashboard",
          title: "Status and next actions",
          description: "Keep the first screen on posture, failures, and the next surface.",
          bodyClassName: "page-grid",
          body: `
            ${card(
              "Gateway status",
              `
                <div class="overview-intro">
                  <section class="overview-callout">
                    <span class="eyebrow">Current posture</span>
                    <h4 class="overview-callout__title">
                      ${escapeHtml(
                        setup.setup_complete
                          ? "Gateway is ready for operator work."
                          : "Bootstrap is still open.",
                      )}
                    </h4>
                    <p class="muted">
                      ${escapeHtml(
                        setup.setup_complete
                          ? `Next: ${nextSurface}.`
                          : setup.persistence_enabled === false
                            ? "Finish GigaChat auth and gateway auth first. This runtime reads env only."
                            : "Finish persisted setup, GigaChat auth, and gateway auth first.",
                      )}
                    </p>
                  </section>
                  <div class="overview-stat-grid">
                    ${renderOverviewMetric(
                      "Setup",
                      setup.setup_complete ? "Complete" : "Needs action",
                      setup.setup_complete ? "Bootstrap closed." : "Open Setup.",
                      setup.setup_complete ? "good" : "warn",
                    )}
                    ${renderOverviewMetric(
                      "Requests",
                      formatNumber(requestCount),
                      `${formatNumber(totalTokens)} tokens`,
                    )}
                    ${renderOverviewMetric(
                      "Error rate",
                      formatPercent(errorCount, requestCount),
                      errorCount > 0 ? `${formatNumber(errorCount)} recent errors` : "No recent errors",
                      errorCount > 0 ? "warn" : "good",
                    )}
                    ${renderOverviewMetric(
                      "Providers",
                      formatNumber(enabledProviders.length),
                      topProvider
                        ? `Top: ${String(topProvider.provider ?? "Unknown")}`
                        : "No traffic yet",
                    )}
                  </div>
                  ${renderDefinitionList(
                    [
                      {
                        label: "Runtime mode",
                        value: String(runtime.mode ?? "n/a"),
                        note: setup.setup_complete
                          ? runtimeRecord.docs_enabled
                            ? "Docs stay exposed."
                            : "Docs are disabled."
                          : "Use DEV for bootstrap, then harden before rollout.",
                      },
                      {
                        label: "Provider mix",
                        value: enabledProviders.join(", ") || "none",
                        note: topProvider
                          ? `${String(topProvider.provider ?? "unknown")} carries the most visible traffic.`
                          : "No provider usage yet.",
                      },
                      {
                        label: "Traffic snapshot",
                        value: `${formatNumber(requestCount)} requests / ${formatNumber(totalTokens)} tokens`,
                        note:
                          errorCount > 0
                            ? `${formatNumber(errorCount)} recent errors need review.`
                            : "No recent errors in the rollup.",
                      },
                      {
                        label: "Next surface",
                        value: nextSurface,
                        note:
                          errorCount > 0
                            ? "Stay in Logs or Traffic until failures are explained."
                            : "Open the next surface that matches the task.",
                      },
                    ],
                    "Overview summary is unavailable.",
                  )}
                </div>
              `,
              "panel panel--span-8 panel--measure",
            )}
            ${card(
              "Fast actions",
              `
                <div class="stack overview-aside">
                  <div class="dual-grid">
                    ${
                      setup.setup_complete
                        ? `
                            <a class="button" href="${escapeHtml(pathForPage("playground"))}">Playground</a>
                            <a class="button button--secondary" href="${escapeHtml(pathForPage("traffic"))}">Traffic</a>
                            <a class="button button--secondary" href="${escapeHtml(pathForPage("logs"))}">Logs</a>
                            <a class="button button--secondary" href="${escapeHtml(pathForPage("settings"))}">Settings</a>
                            <a class="button button--secondary" href="${escapeHtml(pathForPage("providers"))}">Providers</a>
                            <a class="button button--secondary" href="${escapeHtml(pathForPage("files-batches"))}">Files & Batches</a>
                          `
                        : `
                            <a class="button" href="${escapeHtml(pathForPage("setup"))}">Setup</a>
                            <a class="button button--secondary" href="${escapeHtml(pathForPage("keys"))}">API Keys</a>
                            <a class="button button--secondary" href="${escapeHtml(pathForPage("settings"))}">Settings</a>
                            <a class="button button--secondary" href="${escapeHtml(pathForPage("system"))}">System</a>
                          `
                    }
                  </div>
                  ${renderStatLines(
                    [
                      {
                        label: "Next move",
                        value: nextSurface,
                        tone: errorCount > 0 || !setup.setup_complete ? "warn" : "good",
                      },
                      {
                        label: "Security posture",
                        value: setup.security_ready ? "ready" : "pending",
                        tone: setup.security_ready ? "good" : "warn",
                      },
                      {
                        label: "Provider posture",
                        value: enabledProviders.join(", ") || "none",
                      },
                      {
                        label: "Tokens observed",
                        value: formatNumber(totalTokens),
                        tone: totalTokens > 0 ? "good" : "default",
                      },
                    ],
                    "Fast actions are unavailable.",
                  )}
                </div>
              `,
              "panel panel--span-4 panel--aside",
            )}
            ${card(
              "Recent issues",
              `
                <div class="stack">
                  ${banner(
                    errorCount > 0
                      ? `${formatNumber(errorCount)} recent errors are visible in the current rollup.`
                      : "No recent errors are visible in the current rollup.",
                    errorCount > 0 ? "warn" : "info",
                  )}
                  ${renderTable(
                    [
                      { label: "When" },
                      { label: "Route" },
                      { label: "Failure" },
                      { label: "Context" },
                      { label: "Handoff" },
                    ],
                    recentErrors.map((event) => {
                      const requestId = String(event.request_id ?? "").trim();
                      return [
                        `<strong>${escapeHtml(formatTimestamp(event.created_at))}</strong><br /><span class="muted">${escapeHtml(requestId || "no request id")}</span>`,
                        `${escapeHtml(String(event.provider ?? "unknown"))}<br /><span class="muted">${escapeHtml(String(event.method ?? "GET"))} ${escapeHtml(String(event.endpoint ?? event.path ?? "n/a"))}</span>`,
                        `<strong>${escapeHtml(String(event.error_type ?? "HTTP error"))}</strong><br /><span class="muted">status ${escapeHtml(formatNumber(event.status_code ?? 0))}</span>`,
                        `${escapeHtml(String(event.model ?? "n/a"))}<br /><span class="muted">${escapeHtml(String(event.api_key_name ?? event.api_key_source ?? "anonymous"))}</span>`,
                        renderRecentErrorActions(requestId),
                      ];
                    }),
                    "No recent errors recorded.",
                  )}
                </div>
              `,
              "panel panel--span-8 panel--measure",
            )}
            ${card(
              "Provider snapshot",
              renderDefinitionList(
                buildProviderSnapshot(providerEntries, topProvider, enabledProviders, requestCount, totalTokens),
                "Provider snapshot is unavailable.",
              ),
              "panel panel--span-4 panel--aside",
            )}
          `,
        }),
        renderPageSection({
          eyebrow: "Handoff",
          title: "Surface map",
          description: "Keep posture details and guides below the main dashboard.",
          bodyClassName: "page-grid",
          body: `
            ${card(
              "Surface handoff",
              renderDefinitionList(
                buildSurfaceHandoffs(
                  setup,
                  requestCount,
                  errorCount,
                  enabledProviders,
                  topProvider,
                  docsEnabled,
                ),
                "Surface handoff is unavailable.",
              ),
              "panel panel--span-4 panel--aside",
            )}
            ${card(
              "Gateway posture",
              renderDefinitionList(
                [
                  {
                    label: "Runtime mode",
                    value: String(runtime.mode ?? "n/a"),
                    note: docsEnabled
                      ? "Operator docs stay exposed."
                      : "Operator docs are disabled.",
                  },
                  {
                    label: "Persistence",
                    value: persistence.value,
                    note: persistence.note,
                  },
                  {
                    label: "GigaChat auth",
                    value: gigachatAuth.value,
                    note: gigachatAuth.note,
                  },
                  {
                    label: "Gateway auth",
                    value: gatewayAuthReady ? "Required" : "Open",
                    note: gatewayAuthReady
                      ? "Client access already depends on a gateway API key."
                      : "Close this before broader exposure.",
                  },
                ],
                "Gateway posture is unavailable.",
              ),
              "panel panel--span-4 panel--aside",
            )}
            ${card(
              "Canonical docs",
              renderGuideLinks(
                [
                  {
                    label: "Docs entry point",
                    href: CANONICAL_DOC_LINKS.index,
                    note: "Start here when you need the canonical docs map instead of another admin surface.",
                  },
                  {
                    label: "Operator guide overview",
                    href: OPERATOR_GUIDE_LINKS.overview,
                    note: "Open only if runtime posture now needs deeper operator guidance.",
                  },
                  {
                    label: "0.x to 1.0 upgrade guide",
                    href: CANONICAL_DOC_LINKS.upgrade,
                    note: "Use this when the instance still reflects pre-1.0 rollout assumptions.",
                  },
                ],
                {
                  collapsibleSummary: "Canonical docs",
                  compact: true,
                  intro: "Use these when the summary still needs canonical product docs.",
                },
              ),
              "panel panel--span-4 panel--aside",
            )}
          `,
        }),
      ],
    }),
  );
}

function formatPercent(part: number, total: number): string {
  if (!Number.isFinite(part) || !Number.isFinite(total) || total <= 0) {
    return "0%";
  }
  return `${((part / total) * 100).toFixed(part === 0 ? 0 : 1)}%`;
}

function renderRecentErrorActions(requestId: string): string {
  if (!requestId) {
    return `<a class="button button--secondary" href="/admin/logs">Open logs</a>`;
  }
  return `
    <div class="toolbar">
      <a class="button button--secondary" href="${escapeHtml(buildLogsUrlForRequest(requestId))}">Logs</a>
      <a class="button button--secondary" href="${escapeHtml(buildTrafficUrlForRequest(requestId))}">Traffic</a>
    </div>
  `;
}

function buildLogsUrlForRequest(requestId: string): string {
  const params = new URLSearchParams();
  if (requestId.trim()) {
    params.set("request_id", requestId.trim());
  }
  const query = params.toString();
  return query ? `/admin/logs?${query}` : "/admin/logs";
}

function buildTrafficUrlForRequest(requestId: string): string {
  const params = new URLSearchParams();
  if (requestId.trim()) {
    params.set("request_id", requestId.trim());
  }
  const query = params.toString();
  return query ? `/admin/traffic?${query}` : "/admin/traffic";
}

function renderOverviewMetric(
  label: string,
  value: string,
  note?: string,
  tone: "default" | "good" | "warn" = "default",
): string {
  const toneClass =
    tone === "good"
      ? "overview-metric overview-metric--good"
      : tone === "warn"
        ? "overview-metric overview-metric--warn"
        : "overview-metric";
  return `
    <article class="${toneClass}">
      <span class="overview-metric__label">${escapeHtml(label)}</span>
      <strong class="overview-metric__value">${escapeHtml(value)}</strong>
      ${note ? `<span class="overview-metric__note">${escapeHtml(note)}</span>` : ""}
    </article>
  `;
}

function describeNextSurface(setup: SetupPayload, errorCount: number, requestCount: number): string {
  if (!setup.setup_complete) {
    return "Setup";
  }
  if (errorCount > 0) {
    return "Logs";
  }
  if (requestCount > 0) {
    return "Traffic";
  }
  return "Playground";
}

function buildProviderSnapshot(
  providerEntries: UsageRow[],
  topProvider: UsageRow | null,
  enabledProviders: string[],
  requestCount: number,
  totalTokens: number,
): Array<{ label: string; value: string; note?: string }> {
  if (!providerEntries.length) {
    return [
      {
        label: "Enabled providers",
        value: enabledProviders.join(", ") || "none",
        note: requestCount
          ? `${formatNumber(requestCount)} requests are recorded, but no provider breakdown is available.`
          : "No provider traffic yet.",
      },
      {
        label: "Observed tokens",
        value: formatNumber(totalTokens),
        note: "Run playground or live traffic to populate rollups.",
      },
    ];
  }

  return providerEntries.slice(0, 4).map((entry, index) => {
    const providerName = String(entry.provider ?? `Provider ${index + 1}`);
    const providerRequests = Number(entry.request_count ?? 0);
    const providerErrors = Number(entry.error_count ?? 0);
    const providerTokens = Number(entry.total_tokens ?? 0);

    return {
      label: index === 0 ? "Lead provider" : providerName,
      value: index === 0 ? providerName : formatNumber(providerRequests),
      note:
        index === 0
          ? `${formatNumber(providerRequests)} requests · ${formatNumber(providerErrors)} errors · ${formatNumber(providerTokens)} tokens`
          : `${formatNumber(providerErrors)} errors · ${formatNumber(providerTokens)} tokens`,
    };
  }).concat(
    topProvider && enabledProviders.length > providerEntries.length
      ? [
          {
            label: "Enabled families",
            value: formatNumber(enabledProviders.length),
            note: "Some enabled providers are not yet represented in the recent usage rollup.",
          },
        ]
      : [],
  );
}

function buildSurfaceHandoffs(
  setup: SetupPayload,
  requestCount: number,
  errorCount: number,
  enabledProviders: string[],
  topProvider: UsageRow | null,
  docsEnabled: boolean,
): Array<{ label: string; value: string; note?: string }> {
  return [
    {
      label: "Playground",
      value: setup.setup_complete ? "Smoke requests" : "Finish bootstrap first",
      note: setup.setup_complete
        ? "Use it for route validation and smoke tests."
        : "Finish persisted auth and gateway auth first.",
    },
    {
      label: "Traffic",
      value: requestCount > 0 ? "Review recent requests" : "Wait for live traffic",
      note:
        requestCount > 0
          ? `${formatNumber(requestCount)} requests are ready for inspection.`
          : "Traffic becomes useful after the first real requests land.",
    },
    {
      label: "Logs",
      value: errorCount > 0 ? "Inspect active failures" : "Use for request-pinned tails",
      note:
        errorCount > 0
          ? `${formatNumber(errorCount)} recent errors make Logs the first escalation surface.`
          : "Open Logs when one request needs deeper tail detail.",
    },
    {
      label: "Providers",
      value: enabledProviders.join(", ") || "none",
      note: topProvider
        ? `${String(topProvider.provider ?? "Unknown")} currently carries the most visible traffic.`
        : docsEnabled
          ? "No provider usage yet; docs stay exposed while posture is still being validated."
          : "No provider usage yet; validate provider posture before rollout.",
    },
  ];
}
