import { banner, card, kpi, renderSetupSteps, renderStatLines, renderTable, } from "../templates.js";
import { asArray, asRecord, escapeHtml, formatNumber } from "../utils.js";
export async function renderSystem(app, token) {
    const [runtime, config, routes, setup] = await Promise.all([
        app.api.json("/admin/api/runtime"),
        app.api.json("/admin/api/config"),
        app.api.json("/admin/api/routes"),
        app.api.json("/admin/api/setup"),
    ]);
    if (!app.isCurrentRender(token)) {
        return;
    }
    const diagnostics = { runtime, config, routes, setup };
    const routeRows = asArray(routes.routes);
    const routeCounts = summarizeRoutes(routeRows);
    const runtimeState = asRecord(runtime.state);
    const configSummary = asRecord(config.summary);
    const warnings = asArray(setup.warnings).map(String);
    app.setHeroActions(`<button class="button button--secondary" id="copy-diagnostics" type="button">Copy diagnostics JSON</button>`);
    app.setContent(`
    ${kpi("Version", String(runtime.app_version ?? "n/a"))}
    ${kpi("Mode", String(runtime.mode ?? "n/a"))}
    ${kpi("Routes", formatNumber(routeRows.length))}
    ${kpi("Store", String(runtime.runtime_store_backend ?? "n/a"))}
    ${card("Setup readiness", `
        <div class="stack">
          ${warnings.map((warning) => banner(warning, "warn")).join("")}
          ${renderStatLines([
        {
            label: "Persisted control-plane config",
            value: setup.persisted ? "yes" : "no",
            tone: setup.persisted ? "good" : "warn",
        },
        {
            label: "GigaChat credentials ready",
            value: setup.gigachat_ready ? "ready" : "missing",
            tone: setup.gigachat_ready ? "good" : "warn",
        },
        {
            label: "Security bootstrap ready",
            value: setup.security_ready ? "ready" : "pending",
            tone: setup.security_ready ? "good" : "warn",
        },
        {
            label: "Setup completed",
            value: setup.setup_complete ? "complete" : "in progress",
            tone: setup.setup_complete ? "good" : "warn",
        },
    ], "Setup status is unavailable.")}
          ${renderSetupSteps(asArray(setup.wizard_steps).map((step) => ({
        id: String(step.id ?? ""),
        label: String(step.label ?? "Step"),
        description: String(step.description ?? ""),
        ready: Boolean(step.ready),
    })))}
        </div>
      `, "panel panel--span-5")}
    ${card("Runtime state", `
        <div class="stack">
          <div>
            <span class="eyebrow">Services</span>
            ${renderBooleanSection(asRecord(runtimeState.services))}
          </div>
          <div>
            <span class="eyebrow">Providers</span>
            ${renderBooleanSection(asRecord(runtimeState.providers))}
          </div>
          <div>
            <span class="eyebrow">Stores</span>
            ${renderSummarySection(asRecord(runtimeState.stores))}
          </div>
        </div>
      `, "panel panel--span-4")}
    ${card("Route posture", renderStatLines([
        { label: "Admin routes", value: formatNumber(routeCounts.admin), tone: "good" },
        { label: "OpenAI routes", value: formatNumber(routeCounts.openai) },
        { label: "Anthropic routes", value: formatNumber(routeCounts.anthropic) },
        { label: "Gemini routes", value: formatNumber(routeCounts.gemini) },
        { label: "System routes", value: formatNumber(routeCounts.system) },
        { label: "Docs / OpenAPI", value: runtime.docs_enabled ? "exposed" : "disabled" },
    ], "Mounted route summary is unavailable."), "panel panel--span-3")}
    ${card("Effective config summary", Object.entries(configSummary)
        .map(([sectionName, sectionValue]) => `
            <div class="stack">
              <span class="eyebrow">${escapeHtml(sectionName)}</span>
              ${renderSummarySection(asRecord(sectionValue))}
            </div>
          `)
        .join(""), "panel panel--span-7")}
    ${card("Runtime posture", renderStatLines([
        {
            label: "Auth required",
            value: runtime.auth_required ? "yes" : "no",
            tone: runtime.auth_required ? "good" : "warn",
        },
        {
            label: "Enabled providers",
            value: asArray(runtime.enabled_providers).map(String).join(", ") || "none",
        },
        {
            label: "Telemetry",
            value: runtime.telemetry_enabled ? "enabled" : "disabled",
            tone: runtime.telemetry_enabled ? "good" : "default",
        },
        {
            label: "Governance limits",
            value: formatNumber(runtime.governance_limits_configured ?? 0),
        },
        {
            label: "Logs allowlist",
            value: runtime.logs_ip_allowlist_enabled ? "configured" : "open",
        },
        {
            label: "Reasoning / Images",
            value: `${runtime.enable_reasoning ? "reasoning on" : "reasoning off"} · ${runtime.enable_images ? "images on" : "images off"}`,
        },
    ], "Runtime posture metadata is unavailable."), "panel panel--span-5")}
    ${card("Mounted routes", renderTable([
        { label: "Path" },
        { label: "Methods" },
        { label: "Tags" },
        { label: "Schema" },
    ], routeRows.map((row) => [
        `<strong>${escapeHtml(String(row.path ?? "n/a"))}</strong><br /><span class="muted">${escapeHtml(String(row.name ?? "unnamed"))}</span>`,
        escapeHtml(asArray(row.methods).map(String).join(", ") || "n/a"),
        escapeHtml(asArray(row.tags).map(String).join(", ") || "none"),
        escapeHtml(row.include_in_schema ? "included" : "hidden"),
    ]), "No mounted routes were reported by the admin API."), "panel panel--span-7")}
    ${card("Diagnostics export", `
        <div class="stack">
          <p class="muted">This bundle contains runtime, config, setup and route state exactly as reported by the admin APIs.</p>
          <pre class="code-block code-block--tall" id="system-diagnostics">${escapeHtml(JSON.stringify(diagnostics, null, 2))}</pre>
        </div>
      `, "panel panel--span-5")}
  `);
    document.getElementById("copy-diagnostics")?.addEventListener("click", async () => {
        try {
            await navigator.clipboard.writeText(JSON.stringify(diagnostics, null, 2));
            app.pushAlert("Diagnostics copied to clipboard.", "info");
        }
        catch (error) {
            app.pushAlert(error instanceof Error ? error.message : String(error), "danger");
        }
    });
}
function summarizeRoutes(routes) {
    const counts = {
        admin: 0,
        openai: 0,
        anthropic: 0,
        gemini: 0,
        system: 0,
    };
    routes.forEach((route) => {
        const path = String(route.path ?? "");
        if (path.startsWith("/admin")) {
            counts.admin += 1;
        }
        else if (path.startsWith("/messages")) {
            counts.anthropic += 1;
        }
        else if (path.startsWith("/v1beta")) {
            counts.gemini += 1;
        }
        else if (path === "/health" || path === "/ping" || path === "/metrics") {
            counts.system += 1;
        }
        else {
            counts.openai += 1;
        }
    });
    return counts;
}
function renderBooleanSection(section) {
    return renderStatLines(Object.entries(section).map(([key, value]) => ({
        label: key,
        value: value ? "ready" : "missing",
        tone: value ? "good" : "warn",
    })), "No state entries were reported.");
}
function renderSummarySection(section) {
    return renderStatLines(Object.entries(section).map(([key, value]) => ({
        label: key,
        value: summarizeValue(value),
        tone: typeof value === "boolean" && value ? "good" : "default",
    })), "No summary entries were reported.");
}
function summarizeValue(value) {
    if (value === null || value === undefined || value === "") {
        return "empty";
    }
    if (typeof value === "boolean") {
        return value ? "enabled" : "disabled";
    }
    if (typeof value === "number") {
        return formatNumber(value);
    }
    if (Array.isArray(value)) {
        return value.length ? value.map(String).join(", ") : "none";
    }
    if (typeof value === "object") {
        return `${Object.keys(value).length} fields`;
    }
    return String(value);
}
