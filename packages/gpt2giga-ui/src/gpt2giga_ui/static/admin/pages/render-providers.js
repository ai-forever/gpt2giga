import { OPERATOR_GUIDE_LINKS } from "../docs-links.js";
import { pathForPage } from "../routes.js";
import { banner, card, kpi, pill, renderGuideLinks, renderPageFrame, renderPageSection, renderStatLines, renderTable, } from "../templates.js";
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
    const enabledProviderRows = surfaceRows.filter((row) => Boolean(row.enabled));
    const enabledProviders = asArray(runtime.enabled_providers);
    const adminRouteCount = asArray(asRecord(capabilities.admin).routes).length;
    const routeFamilyRows = buildRouteFamilySummaries(routeRows);
    const capabilityRows = buildCapabilityCoverageRows(surfaceRows);
    const inventoryRows = buildProviderInventoryRows(surfaceRows);
    const leadProvider = [...enabledProviderRows].sort((left, right) => Number(right.route_count ?? 0) - Number(left.route_count ?? 0))[0];
    const leadProviderName = String(leadProvider?.name ?? "");
    const warnings = buildProviderWarnings(enabledProviderRows.length, backend);
    const smokeHref = buildPlaygroundUrlForProvider(leadProviderName);
    const trafficHref = buildTrafficUrlForProvider(leadProviderName);
    const logsHref = buildLogsUrlForProvider(leadProviderName);
    app.setHeroActions(`
    <a class="button" href="${escapeHtml(smokeHref)}">Smoke in playground</a>
    <a class="button button--secondary" href="${escapeHtml(trafficHref)}">Provider traffic</a>
    <a class="button button--secondary" href="/admin/settings">Open settings</a>
    <a class="button button--secondary" href="/admin/system">Open system</a>
  `);
    app.setContent(renderPageFrame({
        toolbar: renderProvidersToolbar(enabledProviders, routeRows.length, capabilityRows.length, backend, leadProviderName),
        stats: [
            kpi("Enabled providers", formatNumber(enabledProviders.length)),
            kpi("Mounted routes", formatNumber(routeRows.length)),
            kpi("Capability groups", formatNumber(capabilityRows.length)),
            kpi("Metrics", backend.telemetry_enabled ? "on" : "off"),
        ],
        sections: [
            renderPageSection({
                eyebrow: "Operational Surface",
                title: "Provider inventory",
                description: "Start from the mounted provider inventory, then move into Playground, Traffic, or Settings only for one provider family at a time.",
                actions: `
            <a class="button button--secondary" href="${escapeHtml(smokeHref)}">Playground</a>
            <a class="button button--secondary" href="${escapeHtml(trafficHref)}">Traffic</a>
            <a class="button button--secondary" href="/admin/settings">Settings</a>
          `,
                bodyClassName: "page-grid",
                body: `
            ${card("Provider inventory", `
                <div class="stack">
                  ${renderTable([
                    { label: "Provider" },
                    { label: "Surface" },
                    { label: "Capabilities" },
                    { label: "Routes" },
                    { label: "Next move" },
                    { label: "Actions" },
                ], inventoryRows, "No provider rows were reported by the admin API.")}
                </div>
              `, "panel panel--span-8 panel--measure")}
            ${card("Operational summary", `
                <div class="stack">
                  ${warnings.length ? warnings.join("") : banner("Provider posture is readable. No urgent backend blockers were detected.", "info")}
                  ${renderStatLines([
                    {
                        label: "Lead provider",
                        value: leadProvider ? displayName(leadProvider) : "none",
                        tone: leadProvider ? "good" : "warn",
                    },
                    {
                        label: "Backend modes",
                        value: `${String(backend.gigachat_api_mode ?? "n/a")} / ${String(backend.chat_backend_mode ?? "n/a")}`,
                    },
                    {
                        label: "Responses mode",
                        value: String(backend.responses_backend_mode ?? "n/a"),
                    },
                    {
                        label: "Admin routes",
                        value: formatNumber(adminRouteCount),
                    },
                    {
                        label: "Runtime store",
                        value: String(backend.runtime_store_backend ?? "n/a"),
                    },
                    {
                        label: "Observability sinks",
                        value: asArray(backend.observability_sinks).join(", ") || "none",
                    },
                ], "Provider summary is unavailable.")}
                  <div class="toolbar">
                    <a class="button button--secondary" href="${escapeHtml(smokeHref)}">Playground</a>
                    <a class="button button--secondary" href="${escapeHtml(trafficHref)}">Traffic</a>
                    <a class="button button--secondary" href="${escapeHtml(logsHref)}">Logs</a>
                  </div>
                </div>
              `, "panel panel--span-4 panel--aside")}
          `,
            }),
            renderPageSection({
                eyebrow: "Coverage",
                title: "Capability and route coverage",
                description: "Compare capability groups against mounted route families before opening raw provider-surface diagnostics.",
                bodyClassName: "page-grid",
                body: `
            ${card("Capability coverage", `
                <div class="stack">
                  ${renderTable([
                    { label: "Capability" },
                    { label: "Enabled surfaces" },
                    { label: "Standby surfaces" },
                    { label: "Route sample" },
                ], capabilityRows.map((row) => [
                    `<strong>${escapeHtml(row.label)}</strong>`,
                    `<span class="muted">${escapeHtml(row.enabledSurfaces)}</span>`,
                    `<span class="muted">${escapeHtml(row.standbySurfaces)}</span>`,
                    `<span class="muted">${escapeHtml(row.routeSample)}</span>`,
                ]), "No capability coverage rows were reported by the admin API.")}
                </div>
              `, "panel panel--span-8 panel--measure")}
            ${card("Route families", renderTable([
                    { label: "Family" },
                    { label: "Mounted routes" },
                    { label: "Owner" },
                ], routeFamilyRows.map((group) => [
                    `<strong>${escapeHtml(group.label)}</strong><br /><span class="muted">${escapeHtml(group.samples.join(", ") || "No routes in this family.")}</span>`,
                    `${escapeHtml(formatNumber(group.count))}<br /><span class="muted">${escapeHtml(group.count ? "mounted" : "idle")}</span>`,
                    `<span class="muted">${escapeHtml(group.owner)}</span>`,
                ]), "No mounted routes were reported by the admin API."), "panel panel--span-4 panel--aside")}
          `,
            }),
            renderPageSection({
                eyebrow: "Diagnostics",
                title: "Backend posture and staged diagnostics",
                description: "Keep backend mode summary, troubleshooting guides, and raw provider snapshots as a secondary escalation layer.",
                bodyClassName: "page-grid",
                body: `
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
                ], "Backend capability metadata is unavailable."), "panel panel--span-4 panel--aside")}
            ${card("Staged route diagnostics", `
                <div class="stack">
                  <p class="muted">Open these only when a route-family mismatch remains.</p>
                  <details class="surface details-disclosure" id="providers-route-detail">
                    <summary>Current route-family snapshot</summary>
                    ${renderTable([
                    { label: "Family" },
                    { label: "Mounted routes" },
                    { label: "Examples" },
                    { label: "Owner" },
                ], routeFamilyRows.map((group) => [
                    `<strong>${escapeHtml(group.label)}</strong>`,
                    `${escapeHtml(formatNumber(group.count))}<br /><span class="muted">${escapeHtml(group.count ? "mounted" : "idle")}</span>`,
                    `<span class="muted">${escapeHtml(group.samples.join(", ") || "No routes in this family.")}</span>`,
                    `<span class="muted">${escapeHtml(group.owner)}</span>`,
                ]), "No mounted routes were reported by the admin API.")}
                  </details>
                  <details class="surface details-disclosure">
                    <summary>Full provider surface matrix</summary>
                    ${renderTable([
                    { label: "Surface" },
                    { label: "Mode" },
                    { label: "Capabilities" },
                    { label: "Routes" },
                ], providerRows.map((row) => {
                    const capabilitiesList = readStringList(row.capabilities);
                    const routesList = readStringList(row.routes);
                    return [
                        `<strong>${escapeHtml(displayName(row))}</strong><br /><span class="muted">${escapeHtml(String(row.surface ?? "surface"))}</span>`,
                        row.enabled
                            ? `<strong>enabled</strong><br /><span class="muted">${escapeHtml(String(row.name ?? ""))}</span>`
                            : `<strong>disabled</strong><br /><span class="muted">${escapeHtml(String(row.name ?? ""))}</span>`,
                        `${escapeHtml(formatNumber(capabilitiesList.length))}<br /><span class="muted">${escapeHtml(capabilitiesList.slice(0, 3).join(", ") || "none")}</span>`,
                        `${escapeHtml(formatNumber(row.route_count ?? routesList.length))}<br /><span class="muted">${escapeHtml(routesList.slice(0, 2).join(", ") || "none")}</span>`,
                    ];
                }), "No capability rows were reported by the admin API.")}
                  </details>
                </div>
              `, "panel panel--span-8 panel--measure")}
            ${card("Operator handoff", renderGuideLinks([
                    {
                        label: "Provider surface diagnostics",
                        href: OPERATOR_GUIDE_LINKS.providers,
                        note: "Coverage, route checks, and Settings to Playground to Traffic handoff.",
                    },
                    {
                        label: "Rollout backend v2",
                        href: OPERATOR_GUIDE_LINKS.rolloutV2,
                        note: "Use this when the mismatch is about backend mode selection.",
                    },
                    {
                        label: "Troubleshooting handoff map",
                        href: OPERATOR_GUIDE_LINKS.troubleshooting,
                        note: "Use this when the next surface is still unclear.",
                    },
                ], {
                    compact: true,
                    collapsibleSummary: "Operator guides",
                    intro: "Open only after coverage, smoke, or traffic still leave a mismatch.",
                }), "panel panel--span-12")}
          `,
            }),
        ],
    }));
}
function buildProviderWarnings(enabledProviderCount, backend) {
    const warnings = [];
    if (enabledProviderCount === 0) {
        warnings.push(banner("No provider surface is enabled. Admin and System can mount, but client traffic has no provider path.", "warn"));
    }
    if (!backend.telemetry_enabled) {
        warnings.push(banner("Telemetry is disabled. Provider posture stays config-only until raw logs or traffic.", "warn"));
    }
    if (!backend.governance_enabled) {
        warnings.push(banner("Governance limits are disabled. Throughput is visible, but requests are not constrained.", "info"));
    }
    return warnings;
}
function renderProvidersToolbar(enabledProviders, routeCount, capabilityGroupCount, backend, leadProviderName) {
    const leadProviderLabel = leadProviderName.trim() || "none";
    return `
    <div class="toolbar">
      <span class="muted">Mounted provider families, route ownership, and backend mode posture stay on one page before you open raw diagnostics.</span>
    </div>
    <div class="pill-row">
      ${pill(`Enabled ${formatNumber(enabledProviders.length)}`, enabledProviders.length ? "good" : "warn")}
      ${pill(`Routes ${formatNumber(routeCount)}`)}
      ${pill(`Coverage ${formatNumber(capabilityGroupCount)}`)}
      ${pill(`Lead ${leadProviderLabel}`, leadProviderName.trim() ? "good" : "warn")}
      ${pill(`Telemetry ${backend.telemetry_enabled ? "on" : "off"}`, backend.telemetry_enabled ? "good" : "warn")}
      ${pill(`Governance ${backend.governance_enabled ? "on" : "off"}`)}
    </div>
  `;
}
function buildProviderInventoryRows(rows) {
    return rows.map((row) => {
        const capabilitiesList = readStringList(row.capabilities);
        const routesList = readStringList(row.routes);
        const enabled = Boolean(row.enabled);
        const providerName = String(row.name ?? "");
        return [
            `<strong>${escapeHtml(displayName(row))}</strong><br /><span class="muted">${escapeHtml(providerName || "unknown")}</span>`,
            `${pill(enabled ? "enabled" : "disabled", enabled ? "good" : "warn")}<br /><span class="muted">${escapeHtml(String(row.surface ?? "provider"))}</span>`,
            `${escapeHtml(formatNumber(capabilitiesList.length))}<br /><span class="muted">${escapeHtml(capabilitiesList.slice(0, 4).join(", ") || "No capabilities declared.")}</span>`,
            `${escapeHtml(formatNumber(row.route_count ?? routesList.length))}<br /><span class="muted">${escapeHtml(routesList.slice(0, 3).join(", ") || "No routes declared.")}</span>`,
            `<strong>${escapeHtml(enabled ? "Smoke in playground" : "Enable in Settings")}</strong><br /><span class="muted">${escapeHtml(enabled ? "Validate request flow in Playground or Traffic." : "Restore auth and provider posture first.")}</span>`,
            `
        <div class="toolbar">
          <a class="button button--secondary" href="${escapeHtml(buildPlaygroundUrlForProvider(providerName))}">Playground</a>
          <a class="button button--secondary" href="${escapeHtml(buildTrafficUrlForProvider(providerName))}">Traffic</a>
        </div>
      `,
        ];
    });
}
function buildCapabilityCoverageRows(rows) {
    const definitions = [
        {
            label: "Chat requests",
            capabilities: ["chat_completions", "messages", "generate_content", "stream_generate_content"],
        },
        {
            label: "Responses API",
            capabilities: ["responses"],
        },
        {
            label: "Embeddings",
            capabilities: ["embeddings", "batch_embed_contents"],
        },
        {
            label: "Files",
            capabilities: ["files"],
        },
        {
            label: "Batches",
            capabilities: ["batches", "message_batches"],
        },
        {
            label: "Model discovery",
            capabilities: ["models", "litellm_model_info"],
        },
        {
            label: "Token counting",
            capabilities: ["count_tokens"],
        },
    ];
    return definitions.map((definition) => {
        const matchingRows = rows.filter((row) => readStringList(row.capabilities).some((capability) => definition.capabilities.includes(capability)));
        const enabled = matchingRows.filter((row) => Boolean(row.enabled)).map(displayName);
        const standby = matchingRows.filter((row) => !row.enabled).map(displayName);
        const sampleRoutes = matchingRows.flatMap((row) => readStringList(row.routes)).slice(0, 3);
        return {
            label: definition.label,
            enabledSurfaces: enabled.join(", ") || "none",
            standbySurfaces: standby.join(", ") || "none",
            routeSample: sampleRoutes.join(", ") || "No route sample",
        };
    });
}
function buildRouteFamilySummaries(routes) {
    const groups = {
        admin: [],
        openai: [],
        anthropic: [],
        gemini: [],
        system: [],
    };
    routes.forEach((route) => {
        const path = String(route.path ?? "");
        groups[classifyRoute(path)].push(path);
    });
    const descriptors = [
        { key: "admin", label: "Admin", owner: "Console and admin APIs" },
        { key: "openai", label: "OpenAI", owner: "OpenAI compatibility + LiteLLM" },
        { key: "anthropic", label: "Anthropic", owner: "Anthropic compatibility" },
        { key: "gemini", label: "Gemini", owner: "Gemini compatibility" },
        { key: "system", label: "System", owner: "Health, ping, and metrics" },
    ];
    return descriptors.map(({ key, label, owner }) => ({
        key,
        label,
        owner,
        count: groups[key].length,
        samples: [...new Set(groups[key])].slice(0, 3),
    }));
}
function classifyRoute(path) {
    if (isOperatorSupportRoute(path) || path.startsWith("/admin")) {
        return "admin";
    }
    if (path.startsWith("/messages")) {
        return "anthropic";
    }
    if (path.startsWith("/v1beta") || path.startsWith("/upload/v1beta")) {
        return "gemini";
    }
    if (path === "/health" || path === "/ping" || path === "/metrics") {
        return "system";
    }
    return "openai";
}
function isOperatorSupportRoute(path) {
    return path === "/" || path === "/favicon.ico" || path === "/robots.txt";
}
function readStringList(value) {
    return asArray(value).map(String);
}
function displayName(row) {
    return String(row.display_name ?? row.name ?? "unknown");
}
function buildPlaygroundUrlForProvider(providerName) {
    const presetId = resolvePlaygroundPresetIdForProvider(providerName);
    if (!presetId) {
        return pathForPage("playground");
    }
    const params = new URLSearchParams();
    params.set("preset", presetId);
    return `${pathForPage("playground")}?${params.toString()}`;
}
function buildTrafficUrlForProvider(providerName) {
    const params = new URLSearchParams();
    if (providerName.trim()) {
        params.set("provider", providerName.trim());
    }
    const query = params.toString();
    return query ? `/admin/traffic?${query}` : "/admin/traffic";
}
function buildLogsUrlForProvider(providerName) {
    const params = new URLSearchParams();
    if (providerName.trim()) {
        params.set("provider", providerName.trim());
    }
    const query = params.toString();
    return query ? `/admin/logs?${query}` : "/admin/logs";
}
function resolvePlaygroundPresetIdForProvider(providerName) {
    const normalizedName = providerName.trim().toLowerCase();
    if (!normalizedName) {
        return null;
    }
    if (normalizedName.includes("anthropic")) {
        return "anthropic-messages";
    }
    if (normalizedName.includes("gemini")) {
        return "gemini-stream";
    }
    if (normalizedName.includes("openai")) {
        return "openai-chat-hello";
    }
    return null;
}
