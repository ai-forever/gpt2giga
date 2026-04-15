import { card, renderDefinitionList, renderStatLines, renderTable, } from "../templates.js";
import { asArray, asRecord, escapeHtml, formatNumber, formatTimestamp, } from "../utils.js";
const MAX_SUMMARY_ROWS = 5;
export async function renderOverview(app, token) {
    const [runtime, setup, usageKeys, usageProviders, errors] = await Promise.all([
        app.api.json("/admin/api/runtime"),
        app.api.json("/admin/api/setup"),
        app.api.json("/admin/api/usage/keys"),
        app.api.json("/admin/api/usage/providers"),
        app.api.json("/admin/api/errors/recent?limit=5"),
    ]);
    if (!app.isCurrentRender(token)) {
        return;
    }
    const runtimeRecord = asRecord(runtime);
    const setupRecord = asRecord(setup);
    const summary = asRecord(usageProviders.summary);
    const keyEntries = asArray(usageKeys.entries).slice(0, MAX_SUMMARY_ROWS);
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
    ${card("Next steps", `
        <div class="stack overview-aside">
          <div class="toolbar">
            <a class="button" href="${escapeHtml(setup.setup_complete ? "/admin/playground" : "/admin/setup")}">
              ${escapeHtml(setup.setup_complete ? "Run smoke request" : "Finish setup")}
            </a>
            <a class="button button--secondary" href="/admin/traffic">Inspect traffic</a>
            <a class="button button--secondary" href="/admin/logs">Inspect logs</a>
          </div>
          ${renderStatLines([
        {
            label: "Persisted config",
            value: setup.persisted ? "ready" : "missing",
            tone: setup.persisted ? "good" : "warn",
        },
        {
            label: "GigaChat credentials",
            value: setup.gigachat_ready ? "ready" : "missing",
            tone: setup.gigachat_ready ? "good" : "warn",
        },
        {
            label: "Security bootstrap",
            value: setup.security_ready ? "ready" : "pending",
            tone: setup.security_ready ? "good" : "warn",
        },
        {
            label: "Gateway auth",
            value: runtimeRecord.auth_required ? "required" : "open",
            tone: runtimeRecord.auth_required ? "good" : "warn",
        },
        {
            label: "Telemetry",
            value: runtime.telemetry_enabled ? "enabled" : "disabled",
            tone: runtime.telemetry_enabled ? "good" : "default",
        },
    ], "No readiness metadata is available.")}
          ${renderDefinitionList([
        {
            label: "Focused page",
            value: setup.setup_complete ? "Playground or logs" : "Setup",
            note: setup.setup_complete
                ? "Start with one smoke request, then open logs only if something fails."
                : "Complete bootstrap and credentials before digging into the rest of the console.",
        },
        {
            label: "Providers",
            value: enabledProviders.join(", ") || "none",
            note: topProvider
                ? `${String(topProvider.provider ?? "unknown")} is currently the most visible provider.`
                : "No provider traffic has been recorded yet.",
        },
    ], "No action summary is available.")}
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
function joinObjectKeys(value) {
    const entries = Object.keys(asRecord(value));
    return entries.length ? entries.join(", ") : "none";
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
