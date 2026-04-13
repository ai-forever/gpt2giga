import { banner, card, kpi, pill, renderDefinitionList, renderStatLines, renderTable, } from "../templates.js";
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
    const warnings = buildProviderWarnings(enabledProviderRows.length, backend);
    app.setHeroActions(`
    <a class="button" href="/admin/playground">Smoke in playground</a>
    <a class="button button--secondary" href="/admin/settings">Open settings</a>
    <a class="button button--secondary" href="/admin/setup">Open setup</a>
    <a class="button button--secondary" href="/admin/system">Open system</a>
  `);
    app.setContent(`
    ${kpi("Enabled providers", formatNumber(enabledProviders.length))}
    ${kpi("Mounted routes", formatNumber(routeRows.length))}
    ${kpi("Capability groups", formatNumber(capabilityRows.length))}
    ${kpi("Metrics", backend.telemetry_enabled ? "on" : "off")}
    ${card("Executive summary", `
        <div class="stack">
          ${warnings.length ? warnings.join("") : banner("Provider posture is readable and no urgent backend blockers were detected.", "info")}
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
      `, "panel panel--span-4")}
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
    ${card("Operator handoff", `
        <div class="stack">
          <div class="toolbar">
            <a class="button" href="/admin/playground">Smoke request</a>
            <a class="button button--secondary" href="/admin/traffic">Traffic</a>
            <a class="button button--secondary" href="/admin/logs">Logs</a>
          </div>
          ${renderDefinitionList([
        {
            label: "Setup",
            value: "Provider bootstrap",
            note: "Use Setup when provider access is blocked by missing credentials or bootstrap posture.",
        },
        {
            label: "Settings",
            value: "Runtime toggles",
            note: "Use Settings to change enabled providers, observability sinks, and auth posture.",
        },
        {
            label: "System",
            value: "Full diagnostics",
            note: "System keeps the route/runtime/config bundle when this page suggests a backend mismatch.",
        },
    ], "No handoff guidance is available.")}
        </div>
      `, "panel panel--span-4")}
    ${card("Capability coverage", renderTable([
        { label: "Capability" },
        { label: "Enabled surfaces" },
        { label: "Standby surfaces" },
        { label: "Route sample" },
    ], capabilityRows.map((row) => [
        `<strong>${escapeHtml(row.label)}</strong>`,
        `<span class="muted">${escapeHtml(row.enabledSurfaces)}</span>`,
        `<span class="muted">${escapeHtml(row.standbySurfaces)}</span>`,
        `<span class="muted">${escapeHtml(row.routeSample)}</span>`,
    ]), "No capability coverage rows were reported by the admin API."), "panel panel--span-6")}
    ${card("Mounted route families", renderTable([
        { label: "Family" },
        { label: "Mounted routes" },
        { label: "Examples" },
        { label: "Owner" },
    ], routeFamilyRows.map((group) => [
        `<strong>${escapeHtml(group.label)}</strong>`,
        `${escapeHtml(formatNumber(group.count))}<br /><span class="muted">${escapeHtml(group.count ? "mounted" : "idle")}</span>`,
        `<span class="muted">${escapeHtml(group.samples.join(", ") || "No routes in this family.")}</span>`,
        `<span class="muted">${escapeHtml(group.owner)}</span>`,
    ]), "No mounted routes were reported by the admin API."), "panel panel--span-6")}
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
                    ? "Use Playground or Traffic to validate the enabled compatibility surface."
                    : "Enable this provider family from Settings before expecting mounted routes.",
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
    ${card("Surface matrix", renderTable([
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
    }), "No capability rows were reported by the admin API."), "panel panel--span-12")}
  `);
}
function buildProviderWarnings(enabledProviderCount, backend) {
    const warnings = [];
    if (enabledProviderCount === 0) {
        warnings.push(banner("No provider compatibility surface is enabled. The gateway can mount Admin/System, but client traffic will not have a usable provider family.", "warn"));
    }
    if (!backend.telemetry_enabled) {
        warnings.push(banner("Telemetry is disabled, so provider posture will stay configuration-only until you inspect raw logs or targeted traffic tables.", "warn"));
    }
    if (!backend.governance_enabled) {
        warnings.push(banner("Governance limits are disabled. Throughput posture is visible here, but request shaping is not being constrained by configured limits.", "info"));
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
    if (path.startsWith("/admin")) {
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
