import { banner, card, kpi, pill, renderDefinitionList, renderSetupSteps, renderStatLines, } from "../templates.js";
import { asArray, asRecord, escapeHtml, formatNumber, humanizeField } from "../utils.js";
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
    const routeSummaries = buildRouteSummaries(routeRows);
    const runtimeState = asRecord(runtime.state);
    const configSummary = asRecord(config.summary);
    const warnings = asArray(setup.warnings).map(String);
    const setupSteps = asArray(setup.wizard_steps).map((step) => ({
        id: String(step.id ?? ""),
        label: String(step.label ?? "Step"),
        description: String(step.description ?? ""),
        ready: Boolean(step.ready),
    }));
    const runtimeProviders = asArray(runtime.enabled_providers).map(String);
    const serviceState = asRecord(runtimeState.services);
    const providerState = asRecord(runtimeState.providers);
    const storeState = asRecord(runtimeState.stores);
    app.setHeroActions(`<button class="button button--secondary" id="copy-diagnostics" type="button">Copy diagnostics JSON</button>`);
    app.setContent(`
    ${kpi("Version", String(runtime.app_version ?? "n/a"))}
    ${kpi("Mode", String(runtime.mode ?? "n/a"))}
    ${kpi("Routes", formatNumber(routeRows.length))}
    ${kpi("Store", String(runtime.runtime_store_backend ?? "n/a"))}
    ${card("Operational picture", `
        <div class="triple-grid">
          <section class="surface stack">
            <div class="surface__header">
              <h4>Setup readiness</h4>
              ${pill(setup.setup_complete ? "complete" : "in progress", setup.setup_complete ? "good" : "warn")}
            </div>
            ${warnings.map((warning) => banner(warning, "warn")).join("")}
            ${renderStatLines([
        {
            label: "Persisted control-plane config",
            value: setup.persisted ? "yes" : "no",
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
            label: "Setup status",
            value: setup.setup_complete ? "complete" : "in progress",
            tone: setup.setup_complete ? "good" : "warn",
        },
    ], "Setup status is unavailable.")}
          </section>
          <section class="surface stack">
            <div class="surface__header">
              <h4>Runtime state</h4>
              ${pill(`${formatNumber(countTruthyEntries(serviceState))} ready`, countTruthyEntries(serviceState) ? "good" : "warn")}
            </div>
            <div>
              <span class="eyebrow">Services</span>
              ${renderBooleanSection(serviceState)}
            </div>
            <div>
              <span class="eyebrow">Providers</span>
              ${renderBooleanSection(providerState)}
            </div>
            <div>
              <span class="eyebrow">Stores</span>
              ${renderSummarySection(storeState)}
            </div>
          </section>
          <section class="surface stack">
            <div class="surface__header">
              <h4>Route coverage</h4>
              ${pill(`${formatNumber(routeRows.length)} mounted`)}
            </div>
            ${renderDefinitionList(routeSummaries.map((group) => ({
        label: group.label,
        value: formatNumber(group.count),
        note: group.samples.length ? group.samples.join(", ") : "No routes in this group.",
    })), "No mounted routes were reported by the admin API.")}
          </section>
        </div>
        ${setupSteps.length
        ? `
                <div class="stack">
                  <span class="eyebrow">Checklist</span>
                  ${renderSetupSteps(setupSteps)}
                </div>
              `
        : ""}
      `, "panel panel--span-12")}
    ${card("Runtime posture", renderDefinitionList([
        {
            label: "Auth required",
            value: runtime.auth_required ? "yes" : "no",
        },
        {
            label: "Enabled providers",
            value: runtimeProviders.join(", ") || "none",
        },
        {
            label: "Docs / OpenAPI",
            value: runtime.docs_enabled ? "exposed" : "disabled",
        },
        {
            label: "Telemetry",
            value: runtime.telemetry_enabled ? "enabled" : "disabled",
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
            label: "Reasoning",
            value: runtime.enable_reasoning ? "enabled" : "disabled",
        },
        {
            label: "Images",
            value: runtime.enable_images ? "enabled" : "disabled",
        },
    ], "Runtime posture metadata is unavailable."), "panel panel--span-4")}
    ${card("Effective config", `
        <div class="dual-grid">
          ${Object.entries(configSummary)
        .map(([sectionName, sectionValue]) => {
        const sectionRecord = asRecord(sectionValue);
        return `
                <section class="surface stack">
                  <div class="surface__header">
                    <h4>${escapeHtml(humanizeField(sectionName))}</h4>
                    ${pill(`${formatNumber(Object.keys(sectionRecord).length)} fields`)}
                  </div>
                  ${renderDefinitionList(Object.entries(sectionRecord).map(([key, value]) => ({
            label: humanizeField(key),
            value: summarizeValue(value),
        })), "No summary entries were reported.")}
                </section>
              `;
    })
        .join("")}
        </div>
      `, "panel panel--span-8")}
    ${card("Diagnostics bundle", `
        <div class="stack">
          <p class="muted">
            Copy the full runtime, config, setup, and route payload when you need a precise
            snapshot for debugging.
          </p>
          <details class="surface details-disclosure">
            <summary>Preview raw diagnostics JSON</summary>
            <pre class="code-block code-block--tall" id="system-diagnostics">${escapeHtml(JSON.stringify(diagnostics, null, 2))}</pre>
          </details>
        </div>
      `, "panel panel--span-12")}
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
function buildRouteSummaries(routes) {
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
        { key: "admin", label: "Admin routes" },
        { key: "openai", label: "OpenAI routes" },
        { key: "anthropic", label: "Anthropic routes" },
        { key: "gemini", label: "Gemini routes" },
        { key: "system", label: "System routes" },
    ];
    return descriptors.map(({ key, label }) => ({
        key,
        label,
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
    if (path.startsWith("/v1beta")) {
        return "gemini";
    }
    if (path === "/health" || path === "/ping" || path === "/metrics") {
        return "system";
    }
    return "openai";
}
function countTruthyEntries(section) {
    return Object.values(section).filter(Boolean).length;
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
