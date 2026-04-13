import { card, kpi, renderStatLines, renderTable } from "../templates.js";
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
    const providerDetails = asRecord(capabilities.providers);
    const routeRows = asArray(routes.routes);
    const backend = asRecord(capabilities.backend);
    const enabledProviders = providerRows.filter((row) => row.surface === "provider" && Boolean(row.enabled));
    const adminRouteCount = asArray(asRecord(capabilities.admin).routes).length;
    app.setHeroActions(`
    <button class="button button--secondary" id="reset-provider-route-filter" type="button">Clear route filter</button>
    <a class="button" href="/admin/system">Open system</a>
  `);
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
    ${card("Surface matrix", renderTable([
        { label: "Surface" },
        { label: "Mode" },
        { label: "Capabilities" },
        { label: "Routes" },
        { label: "Inspect" },
    ], providerRows.map((row, index) => [
        `<strong>${escapeHtml(String(row.display_name ?? row.name ?? "unknown"))}</strong><br /><span class="muted">${escapeHtml(String(row.surface ?? "surface"))}</span>`,
        row.enabled
            ? `<strong>enabled</strong><br /><span class="muted">${escapeHtml(String(row.name ?? ""))}</span>`
            : `<strong>disabled</strong><br /><span class="muted">${escapeHtml(String(row.name ?? ""))}</span>`,
        `${escapeHtml(formatNumber(asArray(row.capabilities).length))}<br /><span class="muted">${escapeHtml(asArray(row.capabilities).slice(0, 3).map(String).join(", ") || "none")}</span>`,
        `${escapeHtml(formatNumber(row.route_count ?? 0))}<br /><span class="muted">${escapeHtml(asArray(row.routes).slice(0, 2).map(String).join(", ") || "none")}</span>`,
        `<button class="button button--secondary" data-provider-detail="${index}" type="button">View</button>`,
    ]), "No capability rows were reported by the admin API."), "panel panel--span-8")}
    ${card("Selected surface", `
        <div class="stack">
          ${renderStatLines([
        { label: "Enabled providers", value: formatNumber(enabledProviders.length), tone: "good" },
        {
            label: "Runtime enabled list",
            value: asArray(runtime.enabled_providers).join(", ") || "none",
        },
        {
            label: "Observability sinks",
            value: asArray(backend.observability_sinks).join(", ") || "none",
        },
        {
            label: "Provider detail records",
            value: formatNumber(Object.keys(providerDetails).length),
        },
    ], "No provider summary is available.")}
          <pre class="code-block code-block--tall" id="provider-detail">${escapeHtml(JSON.stringify({
        backend,
        enabled_providers: asArray(runtime.enabled_providers),
    }, null, 2))}</pre>
        </div>
      `, "panel panel--span-4")}
    ${card("Provider detail", Object.entries(providerDetails)
        .map(([providerName, detail]) => {
        const record = asRecord(detail);
        return `
            <article class="step-card">
              <div class="stack">
                <div class="toolbar">
                  <strong>${escapeHtml(String(record.display_name ?? providerName))}</strong>
                  <span class="pill">${escapeHtml(record.enabled ? "enabled" : "disabled")}</span>
                </div>
                <p class="muted">${escapeHtml(asArray(record.capabilities).map(String).join(", ") || "No capabilities declared.")}</p>
                <p class="muted">${escapeHtml(asArray(record.routes).map(String).join(", ") || "No routes declared.")}</p>
              </div>
            </article>
          `;
    })
        .join(""), "panel panel--span-5")}
    ${card("Route inventory", `
        <div class="stack">
          <label class="field">
            <span>Route filter</span>
            <input id="provider-route-filter" placeholder="/admin, /v1, /messages" />
          </label>
          <div id="provider-route-table"></div>
        </div>
      `, "panel panel--span-7")}
  `);
    const detailNode = app.pageContent.querySelector("#provider-detail");
    const routeFilterInput = app.pageContent.querySelector("#provider-route-filter");
    const routeTableNode = app.pageContent.querySelector("#provider-route-table");
    if (!detailNode || !routeFilterInput || !routeTableNode) {
        return;
    }
    const renderRoutes = (filterValue = "") => {
        const normalized = filterValue.trim().toLowerCase();
        const filteredRoutes = routeRows.filter((row) => {
            if (!normalized) {
                return true;
            }
            const haystack = [
                String(row.path ?? ""),
                asArray(row.methods).map(String).join(" "),
                asArray(row.tags).map(String).join(" "),
                String(row.name ?? ""),
            ]
                .join(" ")
                .toLowerCase();
            return haystack.includes(normalized);
        });
        routeTableNode.innerHTML = renderTable([
            { label: "Path" },
            { label: "Methods" },
            { label: "Tags" },
            { label: "Schema" },
        ], filteredRoutes.map((row) => [
            `<strong>${escapeHtml(String(row.path ?? "n/a"))}</strong><br /><span class="muted">${escapeHtml(String(row.name ?? "unnamed"))}</span>`,
            escapeHtml(asArray(row.methods).map(String).join(", ") || "n/a"),
            escapeHtml(asArray(row.tags).map(String).join(", ") || "none"),
            escapeHtml(row.include_in_schema ? "included" : "hidden"),
        ]), "No mounted routes matched the current filter.");
    };
    renderRoutes();
    routeFilterInput.addEventListener("input", () => {
        renderRoutes(routeFilterInput.value);
    });
    document.getElementById("reset-provider-route-filter")?.addEventListener("click", () => {
        routeFilterInput.value = "";
        renderRoutes();
    });
    app.pageContent.querySelectorAll("[data-provider-detail]").forEach((button) => {
        button.addEventListener("click", () => {
            const indexValue = button.dataset.providerDetail;
            if (indexValue === undefined) {
                return;
            }
            const row = providerRows[Number(indexValue)];
            if (!row) {
                return;
            }
            const detailKey = String(row.name ?? "");
            const providerPayload = detailKey && detailKey in providerDetails ? asRecord(providerDetails[detailKey]) : {};
            detailNode.textContent = JSON.stringify({
                matrix_row: row,
                provider_detail: providerPayload,
            }, null, 2);
        });
    });
}
