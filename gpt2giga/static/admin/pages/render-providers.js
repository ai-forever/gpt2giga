import { card, kpi, pill, renderDefinitionList, renderStatLines, renderTable } from "../templates.js";
import { asArray, asRecord, escapeHtml, formatNumber } from "../utils.js";
export async function renderProviders(app, token) {
    const [capabilities, routes, runtime] = await Promise.all([
        app.api.json("/admin/api/capabilities"),
        app.api.json("/admin/api/routes"),
        app.api.json("/admin/api/runtime"),
    ]);
    if (!app.isCurrentRender(token)) {
        return;
    }
    const capabilityMatrix = asRecord(capabilities.matrix);
    const providerRows = asArray(capabilityMatrix.rows);
    const routeRows = asArray(routes.routes);
    const backend = asRecord(capabilities.backend);
    const surfaceRows = providerRows.filter((row) => row.surface === "provider");
    const enabledProviders = asArray(runtime.enabled_providers);
    const adminRouteCount = asArray(asRecord(capabilities.admin).routes).length;
    app.setHeroActions(`<a class="button" href="/admin/system">Open system</a>`);
    app.setContent(`
    ${kpi("Enabled providers", formatNumber(enabledProviders.length))}
    ${kpi("Mounted routes", formatNumber(routeRows.length))}
    ${kpi("Admin routes", formatNumber(adminRouteCount))}
    ${kpi("Metrics", backend.telemetry_enabled ? "on" : "off")}
    ${card("Backend posture", renderStatLines([
        { label: "GigaChat API mode", value: String(backend.gigachat_api_mode ?? "n/a") },
        { label: "Chat backend mode", value: String(backend.chat_backend_mode ?? "n/a") },
        {
            label: "Responses backend mode",
            value: String(backend.responses_backend_mode ?? "n/a"),
        },
        {
            label: "Runtime store backend",
            value: String(backend.runtime_store_backend ?? "n/a"),
        },
        {
            label: "Telemetry",
            value: backend.telemetry_enabled ? "enabled" : "disabled",
            tone: backend.telemetry_enabled ? "good" : "default",
        },
        {
            label: "Governance",
            value: backend.governance_enabled
                ? `${formatNumber(backend.governance_limits_configured ?? 0)} limits`
                : "disabled",
            tone: backend.governance_enabled ? "good" : "default",
        },
    ], "Backend capability metadata is unavailable."), "panel panel--span-4")}
    ${card("Runtime selection", renderDefinitionList([
        {
            label: "Enabled providers",
            value: enabledProviders.join(", ") || "none",
        },
        {
            label: "Observability sinks",
            value: asArray(backend.observability_sinks).join(", ") || "none",
        },
        {
            label: "Runtime store",
            value: String(backend.runtime_store_backend ?? "n/a"),
        },
        {
            label: "Control routes",
            value: formatNumber(adminRouteCount),
            note: "Mounted under /admin.",
        },
    ], "No provider summary is available."), "panel panel--span-4")}
    ${card("Provider coverage", `
        <div class="step-grid">
          ${surfaceRows
        .map((row) => {
        const capabilitiesList = asArray(row.capabilities).map(String);
        const routesList = asArray(row.routes).map(String);
        const enabled = Boolean(row.enabled);
        return `
                <article class="step-card ${enabled ? "step-card--ready" : ""}">
                  ${pill(enabled ? "enabled" : "disabled", enabled ? "good" : "warn")}
                  <h4>${escapeHtml(String(row.display_name ?? row.name ?? "unknown"))}</h4>
                  <p class="muted">${escapeHtml(capabilitiesList.join(", ") || "No capabilities declared.")}</p>
                  <p class="muted">${escapeHtml(`${formatNumber(row.route_count ?? routesList.length)} routes`)}</p>
                </article>
              `;
    })
        .join("")}
        </div>
      `, "panel panel--span-4")}
    ${card("Surface matrix", renderTable([
        { label: "Surface" },
        { label: "Mode" },
        { label: "Capabilities" },
        { label: "Routes" },
    ], providerRows.map((row) => [
        `<strong>${escapeHtml(String(row.display_name ?? row.name ?? "unknown"))}</strong><br /><span class="muted">${escapeHtml(String(row.surface ?? "surface"))}</span>`,
        row.enabled
            ? `<strong>enabled</strong><br /><span class="muted">${escapeHtml(String(row.name ?? ""))}</span>`
            : `<strong>disabled</strong><br /><span class="muted">${escapeHtml(String(row.name ?? ""))}</span>`,
        `${escapeHtml(formatNumber(asArray(row.capabilities).length))}<br /><span class="muted">${escapeHtml(asArray(row.capabilities).slice(0, 3).map(String).join(", ") || "none")}</span>`,
        `${escapeHtml(formatNumber(row.route_count ?? 0))}<br /><span class="muted">${escapeHtml(asArray(row.routes).slice(0, 2).map(String).join(", ") || "none")}</span>`,
    ]), "No capability rows were reported by the admin API."), "panel panel--span-12")}
  `);
}
