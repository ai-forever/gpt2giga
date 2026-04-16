import { WORKFLOW_META, pathForPage } from "../routes.js";
import { card, pill, renderDefinitionList, renderTable, } from "../templates.js";
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
        ? "Gateway is ready for guided operator work."
        : "Gateway still needs a first-run pass.")}
            </h4>
            <p class="muted">
              ${escapeHtml(setup.setup_complete
        ? "Core bootstrap steps are in place. Focus on smoke traffic, logs, and provider coverage."
        : "Finish persisted settings, configure GigaChat credentials, and close the auth bootstrap before treating the gateway as production-ready.")}
            </p>
          </section>
          <div class="overview-stat-grid">
            ${renderOverviewMetric("Setup", setup.setup_complete ? "Complete" : "Needs action", setup.setup_complete ? "Bootstrap and security are in place." : "Open Setup to finish the first-run flow.", setup.setup_complete ? "good" : "warn")}
            ${renderOverviewMetric("Requests", formatNumber(requestCount), `${formatNumber(totalTokens)} total tokens observed.`)}
            ${renderOverviewMetric("Error rate", formatPercent(errorCount, requestCount), errorCount > 0 ? `${formatNumber(errorCount)} recent errors need inspection.` : "No recent errors in the usage rollup.", errorCount > 0 ? "warn" : "good")}
            ${renderOverviewMetric("Providers", formatNumber(enabledProviders.length), topProvider
        ? `${String(topProvider.provider ?? "Unknown")} is currently the busiest provider.`
        : "No provider traffic has been recorded yet.")}
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
      `, "panel panel--span-8")}
    ${card("Operator workflows", `
        <div class="stack overview-aside">
          <p class="muted">The console is grouped by operator workflow. Start from the smallest surface that answers the question, then branch deeper only if the current summary still leaves ambiguity.</p>
          <div class="workflow-grid">
            ${renderWorkflowCard({
        workflow: "start",
        title: setup.setup_complete
            ? "Bootstrap is complete"
            : "Finish the first-run path",
        note: setup.setup_complete
            ? "Stay on the guided path: overview first, then one playground smoke request before opening deeper diagnostics."
            : "Persist the control-plane target, configure GigaChat auth, and close the bootstrap gap before treating the gateway as ready.",
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
        title: "Persist operator posture",
        note: "Use the configuration surfaces for observability, provider posture, and auth rotation instead of editing environment files by hand.",
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
        title: errorCount > 0 ? "Recent traffic needs inspection" : "Keep observation summary-first",
        note: errorCount > 0
            ? "Traffic narrows the request window first. Once one request id matters, open Logs with the same context instead of tailing the whole file."
            : "Traffic stays the broad request view, while Logs is the deep dive only after a single request or failure is worth following.",
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
            ? "Advanced diagnostic surfaces are available"
            : "Provider posture still needs validation",
        note: "Use System and Providers when config, routes, or runtime posture feel inconsistent. Files & Batches stays here as the advanced workbench for stored inputs and batch jobs.",
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
      `, "panel panel--span-4")}
    ${recentErrors.length
        ? card("Recent errors", renderTable([
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
        }), "No recent errors recorded."), "panel panel--span-12")
        : ""}
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
      <span class="overview-metric__note">${escapeHtml(note)}</span>
    </article>
  `;
}
function renderWorkflowCard(options) {
    const workflow = WORKFLOW_META[options.workflow];
    return `
    <article class="workflow-card">
      <div class="workflow-card__header">
        <span class="eyebrow">${escapeHtml(workflow.label)}</span>
        <h4>${escapeHtml(options.title)}</h4>
        <p>${escapeHtml(options.note)}</p>
      </div>
      <div class="pill-row">${options.pills.join("")}</div>
      <div class="workflow-card__actions">
        ${options.actions
        .map((action) => `<a class="button${action.primary ? "" : " button--secondary"}" href="${escapeHtml(action.href)}">${escapeHtml(action.label)}</a>`)
        .join("")}
      </div>
    </article>
  `;
}
