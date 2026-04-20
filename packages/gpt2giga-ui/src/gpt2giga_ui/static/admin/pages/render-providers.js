import { OPERATOR_GUIDE_LINKS } from "../docs-links.js";
import { pathForPage } from "../routes.js";
import { banner, card, kpi, pill, renderDefinitionList, renderGuideLinks, renderPageFrame, renderPageSection, renderStatLines, renderTable, renderWorkflowCard, } from "../templates.js";
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
    const leadProvider = [...enabledProviderRows].sort((left, right) => Number(right.route_count ?? 0) - Number(left.route_count ?? 0))[0];
    const leadProviderName = String(leadProvider?.name ?? "");
    const warnings = buildProviderWarnings(enabledProviderRows.length, backend);
    const smokeHref = pathForPage("playground");
    const trafficHref = buildTrafficUrlForProvider(leadProviderName);
    const logsHref = buildLogsUrlForProvider(leadProviderName);
    app.setHeroActions(`
    <a class="button" href="${escapeHtml(smokeHref)}">Smoke in playground</a>
    <a class="button button--secondary" href="${escapeHtml(trafficHref)}">Provider traffic</a>
    <a class="button button--secondary" href="/admin/settings">Open settings</a>
    <a class="button button--secondary" href="/admin/system">Open system</a>
  `);
    app.setContent(renderPageFrame({
        stats: [
            kpi("Enabled providers", formatNumber(enabledProviders.length)),
            kpi("Mounted routes", formatNumber(routeRows.length)),
            kpi("Capability groups", formatNumber(capabilityRows.length)),
            kpi("Metrics", backend.telemetry_enabled ? "on" : "off"),
        ],
        sections: [
            renderPageSection({
                eyebrow: "Posture",
                title: "Provider posture and next actions",
                description: "Keep enabled-provider posture and the next operator move on the same screen before opening route diagnostics.",
                bodyClassName: "page-grid",
                body: `
            ${card("Executive summary", `
                <div class="stack">
                  ${warnings.length ? warnings.join("") : banner("Provider posture is readable. No urgent backend blockers were detected.", "info")}
                  ${renderDefinitionList([
                    {
                        label: "Enabled provider mix",
                        value: enabledProviders.join(", ") || "none",
                        note: leadProvider
                            ? `${displayName(leadProvider)} currently owns the widest mounted provider surface.`
                            : "No provider surface is enabled yet.",
                    },
                    {
                        label: "Backend modes",
                        value: `${String(backend.gigachat_api_mode ?? "n/a")} / ${String(backend.chat_backend_mode ?? "n/a")}`,
                        note: `Responses mode: ${String(backend.responses_backend_mode ?? "n/a")}.`,
                    },
                    {
                        label: "Operator surfaces",
                        value: `${formatNumber(adminRouteCount)} admin routes / ${formatNumber(routeRows.length)} total`,
                        note: "System and Admin surfaces stay mounted even when provider families are reduced.",
                    },
                    {
                        label: "Runtime store",
                        value: String(backend.runtime_store_backend ?? "n/a"),
                        note: asArray(backend.observability_sinks).join(", ") || "No observability sinks are configured.",
                    },
                ], "Provider summary is unavailable.")}
                </div>
              `, "panel panel--span-8 panel--measure")}
            ${card("Provider workflows", `
                <div class="stack">
                  <div class="workflow-grid">
                    ${renderWorkflowCard({
                    workflow: "configure",
                    compact: true,
                    title: enabledProviderRows.length ? "Adjust provider posture" : "Enable a provider family first",
                    note: enabledProviderRows.length
                        ? "Settings owns toggles and auth."
                        : "Use Setup or Settings to restore a provider path.",
                    pills: [
                        pill(`Enabled: ${formatNumber(enabledProviderRows.length)}`, enabledProviderRows.length ? "good" : "warn"),
                        pill(`Telemetry: ${backend.telemetry_enabled ? "on" : "off"}`, backend.telemetry_enabled ? "good" : "warn"),
                        pill(`Governance: ${backend.governance_enabled ? "on" : "off"}`),
                    ],
                    actions: [
                        { label: "Settings", href: pathForPage("settings"), primary: true },
                        { label: "Setup", href: pathForPage("setup") },
                    ],
                })}
                    ${renderWorkflowCard({
                    workflow: "start",
                    compact: true,
                    title: "Smoke the mounted provider surface",
                    note: leadProvider
                        ? `${displayName(leadProvider)} currently exposes the widest surface.`
                        : "Use Playground after the first provider is enabled.",
                    pills: [
                        pill(`Lead provider: ${leadProvider ? displayName(leadProvider) : "n/a"}`),
                        pill(`Routes: ${formatNumber(routeRows.length)}`),
                        pill(`Capabilities: ${formatNumber(capabilityRows.length)}`),
                    ],
                    actions: [
                        { label: "Playground", href: smokeHref, primary: true },
                        { label: "System", href: pathForPage("system") },
                    ],
                })}
                    ${renderWorkflowCard({
                    workflow: "observe",
                    compact: true,
                    title: "Confirm the live request path",
                    note: leadProvider
                        ? "Traffic opens scoped to the lead provider."
                        : "Wait until a provider is enabled.",
                    pills: [
                        pill(`Lead route owner: ${leadProvider ? displayName(leadProvider) : "none"}`),
                        pill(`Admin routes: ${formatNumber(adminRouteCount)}`),
                        pill(`Store: ${String(backend.runtime_store_backend ?? "n/a")}`),
                    ],
                    actions: [
                        { label: "Traffic", href: trafficHref, primary: true },
                        { label: "Logs", href: logsHref },
                    ],
                })}
                  </div>
                </div>
              `, "panel panel--span-4 panel--aside")}
          `,
            }),
            renderPageSection({
                eyebrow: "Coverage",
                title: "Coverage table and provider briefs",
                description: "Use the capability matrix for fast scanning, then drop into individual provider briefs only when you need per-family detail.",
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
            ${card("Provider briefs", `
                <div class="step-grid">
                  ${surfaceRows
                    .map((row) => {
                    const capabilitiesList = readStringList(row.capabilities);
                    const routesList = readStringList(row.routes);
                    const enabled = Boolean(row.enabled);
                    const providerName = String(row.name ?? "");
                    return `
                        <article class="step-card ${enabled ? "step-card--ready" : ""}">
                          ${pill(enabled ? "enabled" : "disabled", enabled ? "good" : "warn")}
                          <h4>${escapeHtml(displayName(row))}</h4>
                          ${renderDefinitionList([
                        {
                            label: "Capabilities",
                            value: formatNumber(capabilitiesList.length),
                            note: capabilitiesList.slice(0, 4).join(", ") || "No capabilities declared.",
                        },
                        {
                            label: "Declared routes",
                            value: formatNumber(row.route_count ?? routesList.length),
                            note: routesList.slice(0, 3).join(", ") || "No routes declared.",
                        },
                        {
                            label: "Best next step",
                            value: enabled ? "Smoke in playground" : "Check Settings",
                            note: enabled
                                ? "Use Playground or Traffic to validate it."
                                : "Enable this family in Settings first.",
                        },
                    ], "No provider details were reported.")}
                          <div class="toolbar">
                            <a class="button button--secondary" href="/admin/playground">Playground</a>
                            <a class="button button--secondary" href="${escapeHtml(buildTrafficUrlForProvider(providerName))}">Traffic</a>
                          </div>
                        </article>
                      `;
                })
                    .join("")}
                </div>
              `, "panel panel--span-12")}
          `,
            }),
            renderPageSection({
                eyebrow: "Diagnostics",
                title: "Guides and route diagnostics",
                description: "Keep troubleshooting links next to the full route-family and provider-surface snapshots for escalation work.",
                bodyClassName: "page-grid",
                body: `
            ${card("Guide and troubleshooting", renderGuideLinks([
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
                }), "panel panel--span-4 panel--aside")}
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
