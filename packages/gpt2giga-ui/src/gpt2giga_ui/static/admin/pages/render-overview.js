import { OPERATOR_GUIDE_LINKS } from "../docs-links.js";
import { pathForPage } from "../routes.js";
import { card, pill, renderDefinitionList, renderGuideLinks, renderTable, renderWorkflowCard, } from "../templates.js";
import { asArray, asRecord, escapeHtml, formatNumber, formatTimestamp, } from "../utils.js";
const MAX_SUMMARY_ROWS = 5;
export async function renderOverview(app, token) {
    const [runtime, setup, usageProviders, errors] = await Promise.all([
        app.api.json("/admin/api/runtime"),
        app.api.json("/admin/api/setup"),
        app.api.json("/admin/api/usage/providers"),
        app.api.json("/admin/api/errors/recent?limit=5"),
    ]);
    if (!app.isCurrentRender(token)) {
        return;
    }
    const runtimeRecord = asRecord(runtime);
    const summary = asRecord(usageProviders.summary);
    const providerEntries = asArray(usageProviders.entries).slice(0, MAX_SUMMARY_ROWS);
    const recentErrors = asArray(errors.events)
        .slice(-MAX_SUMMARY_ROWS)
        .reverse();
    const enabledProviders = asArray(runtimeRecord.enabled_providers);
    const requestCount = Number(summary.request_count ?? 0);
    const errorCount = Number(summary.error_count ?? 0);
    const totalTokens = Number(summary.total_tokens ?? 0);
    const topProvider = providerEntries[0] ?? null;
    app.setHeroActions(setup.setup_complete
        ? `
          <a class="button" href="/admin/playground">Try playground</a>
          <a class="button button--secondary" href="/admin/logs">Open logs</a>
          <a class="button button--secondary" href="/admin/settings">Open settings</a>
        `
        : `
          <a class="button" href="/admin/setup">Open setup wizard</a>
          <a class="button button--secondary" href="/admin/keys">Open API keys</a>
          <a class="button button--secondary" href="/admin/settings">Open settings</a>
        `);
    app.setContent(`
    ${card("Gateway status", `
        <div class="overview-intro">
          <section class="overview-callout">
            <span class="eyebrow">Current posture</span>
            <h4 class="overview-callout__title">
              ${escapeHtml(setup.setup_complete
        ? "Gateway is ready for operator work."
        : "Gateway still needs setup.")}
            </h4>
            <p class="muted">
              ${escapeHtml(setup.setup_complete
        ? "Use playground, traffic, or settings as the next step."
        : "Finish setup, GigaChat credentials, and gateway auth first.")}
            </p>
          </section>
          <div class="overview-stat-grid">
            ${renderOverviewMetric("Setup", setup.setup_complete ? "Complete" : "Needs action", setup.setup_complete ? "Bootstrap closed." : "Open Setup.", setup.setup_complete ? "good" : "warn")}
            ${renderOverviewMetric("Requests", formatNumber(requestCount), `${formatNumber(totalTokens)} tokens`)}
            ${renderOverviewMetric("Error rate", formatPercent(errorCount, requestCount), errorCount > 0 ? `${formatNumber(errorCount)} recent errors` : "No recent errors", errorCount > 0 ? "warn" : "good")}
            ${renderOverviewMetric("Providers", formatNumber(enabledProviders.length), topProvider
        ? `Top: ${String(topProvider.provider ?? "Unknown")}`
        : "No traffic yet")}
          </div>
          ${renderDefinitionList([
        {
            label: "Runtime mode",
            value: String(runtime.mode ?? "n/a"),
            note: setup.setup_complete
                ? runtimeRecord.docs_enabled
                    ? "Docs remain exposed in the current runtime."
                    : "Docs are disabled in the current runtime."
                : "Use DEV mode for bootstrap, then harden before production exposure.",
        },
        {
            label: "Provider mix",
            value: enabledProviders.join(", ") || "none",
            note: topProvider
                ? `${String(topProvider.provider ?? "unknown")} currently carries the most visible traffic.`
                : "No provider usage has been recorded yet.",
        },
        {
            label: "Traffic snapshot",
            value: `${formatNumber(requestCount)} requests / ${formatNumber(totalTokens)} tokens`,
            note: errorCount > 0
                ? `${formatNumber(errorCount)} recent errors require inspection.`
                : "No recent errors are recorded in the provider usage rollup.",
        },
    ], "Overview summary is unavailable.")}
        </div>
      `, "panel panel--span-8 panel--measure")}
    ${card("Workflow handoff", `
        <div class="stack overview-aside">
          <div class="workflow-grid">
            ${renderWorkflowCard({
        workflow: "start",
        title: setup.setup_complete
            ? "Run setup or playground"
            : "Finish setup",
        compact: true,
        pills: [
            pill(`Persisted: ${setup.persisted ? "ready" : "missing"}`, setup.persisted ? "good" : "warn"),
            pill(`GigaChat: ${setup.gigachat_ready ? "ready" : "missing"}`, setup.gigachat_ready ? "good" : "warn"),
            pill(`Security: ${setup.security_ready ? "ready" : "pending"}`, setup.security_ready ? "good" : "warn"),
        ],
        actions: setup.setup_complete
            ? [
                { label: "Overview", href: pathForPage("overview") },
                { label: "Playground", href: pathForPage("playground"), primary: true },
            ]
            : [
                { label: "Overview", href: pathForPage("overview") },
                { label: "Setup", href: pathForPage("setup"), primary: true },
            ],
    })}
            ${renderWorkflowCard({
        workflow: "configure",
        title: "Open settings or keys",
        compact: true,
        pills: [
            pill(`Gateway auth: ${runtimeRecord.auth_required ? "required" : "open"}`, runtimeRecord.auth_required ? "good" : "warn"),
            pill(`Telemetry: ${runtime.telemetry_enabled ? "enabled" : "disabled"}`, runtime.telemetry_enabled ? "good" : "default"),
            pill(`Providers: ${enabledProviders.length || 0}`),
        ],
        actions: [
            { label: "Settings", href: pathForPage("settings"), primary: true },
            { label: "API Keys", href: pathForPage("keys") },
        ],
    })}
            ${renderWorkflowCard({
        workflow: "observe",
        title: errorCount > 0 ? "Inspect traffic or logs" : "Open traffic or logs",
        compact: true,
        pills: [
            pill(`Requests: ${formatNumber(requestCount)}`),
            pill(`Errors: ${formatNumber(errorCount)}`, errorCount > 0 ? "warn" : "good"),
            pill(`Tokens: ${formatNumber(totalTokens)}`),
        ],
        actions: [
            { label: "Traffic", href: pathForPage("traffic"), primary: true },
            { label: "Logs", href: pathForPage("logs") },
        ],
    })}
            ${renderWorkflowCard({
        workflow: "diagnose",
        title: enabledProviders.length
            ? "Open advanced diagnostics"
            : "Validate provider posture",
        compact: true,
        pills: [
            pill(`Providers: ${enabledProviders.join(", ") || "none"}`),
            pill(`Docs: ${runtimeRecord.docs_enabled ? "exposed" : "disabled"}`),
            pill(`Top provider: ${String(topProvider?.provider ?? "n/a")}`),
        ],
        actions: [
            { label: "System", href: pathForPage("system"), primary: true },
            { label: "Providers", href: pathForPage("providers") },
            { label: "Files & Batches", href: pathForPage("files-batches") },
        ],
    })}
          </div>
        </div>
      `, "panel panel--span-4 panel--aside")}
    ${card("Recent error handoff", `
        <div class="stack">
          ${renderTable([
        { label: "When" },
        { label: "Route" },
        { label: "Failure" },
        { label: "Context" },
        { label: "Handoff" },
    ], recentErrors.map((event) => {
        const requestId = String(event.request_id ?? "").trim();
        return [
            `<strong>${escapeHtml(formatTimestamp(event.created_at))}</strong><br /><span class="muted">${escapeHtml(requestId || "no request id")}</span>`,
            `${escapeHtml(String(event.provider ?? "unknown"))}<br /><span class="muted">${escapeHtml(String(event.method ?? "GET"))} ${escapeHtml(String(event.endpoint ?? event.path ?? "n/a"))}</span>`,
            `<strong>${escapeHtml(String(event.error_type ?? "HTTP error"))}</strong><br /><span class="muted">status ${escapeHtml(formatNumber(event.status_code ?? 0))}</span>`,
            `${escapeHtml(String(event.model ?? "n/a"))}<br /><span class="muted">${escapeHtml(String(event.api_key_name ?? event.api_key_source ?? "anonymous"))}</span>`,
            renderRecentErrorActions(requestId),
        ];
    }), "No recent errors recorded.")}
        </div>
      `, "panel panel--span-8 panel--measure")}
    ${card("Guide and troubleshooting", renderGuideLinks([
        {
            label: "Overview workflow guide",
            href: OPERATOR_GUIDE_LINKS.overview,
            note: "Use the operator guide when the workflow cards still leave the next page-to-page handoff unclear.",
        },
        {
            label: "Traffic workflow guide",
            href: OPERATOR_GUIDE_LINKS.traffic,
            note: "Open the Traffic playbook when the next step is broad request review rather than a request-pinned log dive.",
        },
        {
            label: "Troubleshooting handoff map",
            href: OPERATOR_GUIDE_LINKS.troubleshooting,
            note: "Use the escalation map when the summary cards still do not clearly point at the next operator surface.",
        },
    ], {
        collapsibleSummary: "Operator guides",
        compact: true,
        intro: "Open these only when the summary still does not point to the next page.",
    }), "panel panel--span-4 panel--aside")}
  `);
}
function formatPercent(part, total) {
    if (!Number.isFinite(part) || !Number.isFinite(total) || total <= 0) {
        return "0%";
    }
    return `${((part / total) * 100).toFixed(part === 0 ? 0 : 1)}%`;
}
function renderRecentErrorActions(requestId) {
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
function buildLogsUrlForRequest(requestId) {
    const params = new URLSearchParams();
    if (requestId.trim()) {
        params.set("request_id", requestId.trim());
    }
    const query = params.toString();
    return query ? `/admin/logs?${query}` : "/admin/logs";
}
function buildTrafficUrlForRequest(requestId) {
    const params = new URLSearchParams();
    if (requestId.trim()) {
        params.set("request_id", requestId.trim());
    }
    const query = params.toString();
    return query ? `/admin/traffic?${query}` : "/admin/traffic";
}
function renderOverviewMetric(label, value, note, tone = "default") {
    const toneClass = tone === "good"
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
