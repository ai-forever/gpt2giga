import { OPERATOR_GUIDE_LINKS } from "../docs-links.js";
import { pathForPage } from "../routes.js";
import { banner, card, kpi, pill, renderDefinitionList, renderFormSection, renderGuideLinks, renderJson, renderTable, renderWorkflowCard, } from "../templates.js";
import { asArray, asRecord, csv, escapeHtml, formatNumber, parseCsv } from "../utils.js";
export async function renderKeys(app, token) {
    const keys = await app.api.json("/admin/api/keys");
    if (!app.isCurrentRender(token)) {
        return;
    }
    const global = asRecord(keys.global);
    const globalUsage = asRecord(global.usage);
    const scoped = asArray(keys.scoped);
    const scopedRequestCount = scoped.reduce((total, item) => total + readUsageCount(asRecord(item.usage).request_count), 0);
    const scopedRestrictionCount = scoped.filter(hasScopedRestrictions).length;
    const totalRequestCount = readUsageCount(globalUsage.request_count) + scopedRequestCount;
    app.setHeroActions(`
    <button class="button" id="rotate-global-key" type="button">Rotate global key</button>
    <a class="button button--secondary" href="${escapeHtml(pathForPage("traffic-usage"))}">Open usage traffic</a>
    <a class="button button--secondary" href="${escapeHtml(pathForPage("playground"))}">Smoke in playground</a>
  `);
    app.setContent(`
    ${kpi("Global key", global.configured ? "configured" : "missing")}
    ${kpi("Scoped keys", formatNumber(scoped.length))}
    ${kpi("Restricted scopes", formatNumber(scopedRestrictionCount))}
    ${kpi("Observed requests", formatNumber(totalRequestCount))}
    ${card("Executive summary", `
        <div class="stack">
          ${renderKeysBanner(global, scoped)}
          ${renderDefinitionList([
        {
            label: "Global gateway posture",
            value: global.configured ? "ready" : "missing",
            note: global.configured
                ? `Preview ${String(global.key_preview ?? "hidden")} is staged as the broad fallback credential.`
                : "Rotate a global key if you need one broad credential before handing out narrower scoped keys.",
        },
        {
            label: "Scoped inventory",
            value: formatNumber(scoped.length),
            note: scoped.length
                ? `${formatNumber(scopedRestrictionCount)} keys currently enforce provider, endpoint, or model restrictions.`
                : "No scoped keys exist yet, so every client currently depends on the global key path.",
        },
        {
            label: "Recent usage signal",
            value: `${formatNumber(totalRequestCount)} observed requests`,
            note: totalRequestCount
                ? "Usage is aggregated from the runtime counters already visible in Traffic > Usage."
                : "No requests have been attributed to stored keys yet.",
        },
        {
            label: "Fastest next handoff",
            value: global.configured || scoped.length ? "Playground or Traffic" : "Create a key first",
            note: global.configured || scoped.length
                ? "Smoke one known request in Playground, then confirm attribution in Traffic > Usage."
                : "This page stays key-first until at least one reusable credential exists.",
        },
    ], "Key posture is unavailable.")}
        </div>
      `, "panel panel--span-8 panel--measure")}
    ${card("Key workflows", `
        <div class="stack">
          <div class="workflow-grid">
            ${renderWorkflowCard({
        workflow: "configure",
        compact: true,
        title: global.configured ? "Rotate the global fallback" : "Create the first global fallback",
        note: global.configured ? "Keep it broad only when needed." : "Use it as the first recovery path.",
        pills: [
            pill(`Global: ${global.configured ? "ready" : "missing"}`, global.configured ? "good" : "warn"),
            pill(`Scoped: ${formatNumber(scoped.length)}`),
            pill(`Observed requests: ${formatNumber(totalRequestCount)}`),
        ],
        actions: [
            { label: "Rotate global key", href: "#rotate-global-key", primary: true },
            { label: "Security settings", href: pathForPage("settings-security") },
        ],
    })}
            ${renderWorkflowCard({
        workflow: "start",
        compact: true,
        title: scoped.length ? "Issue a client-specific key" : "Create the first scoped key",
        note: scoped.length ? "Tighten provider, endpoint, or model reach." : "Keep client access narrow from the start.",
        pills: [
            pill(`Restricted scopes: ${formatNumber(scopedRestrictionCount)}`),
            pill(`Preview: ${String(global.key_preview ?? "none")}`),
            pill(`Traffic: ${totalRequestCount ? "warm" : "idle"}`, totalRequestCount ? "good" : "default"),
        ],
        actions: [
            { label: "Create scoped key", href: "#scoped-key-form", primary: true },
            { label: "Playground", href: pathForPage("playground") },
        ],
    })}
            ${renderWorkflowCard({
        workflow: "observe",
        compact: true,
        title: "Confirm attribution after one request",
        note: "Use Traffic as the proof surface.",
        pills: [
            pill(`Global requests: ${formatNumber(readUsageCount(globalUsage.request_count))}`),
            pill(`Scoped requests: ${formatNumber(scopedRequestCount)}`),
            pill(`Keys with usage: ${formatNumber(countKeysWithUsage(global, scoped))}`),
        ],
        actions: [
            { label: "Traffic usage", href: pathForPage("traffic-usage"), primary: true },
            { label: "Logs", href: pathForPage("logs") },
        ],
    })}
          </div>
        </div>
      `, "panel panel--span-4 panel--aside")}
    ${card("Create scoped key", `
        <form id="scoped-key-form" class="form-shell">
          <div class="form-shell__intro">
            <span class="eyebrow">Scoped handoff</span>
            <p class="muted">Create one narrow client key.</p>
          </div>
          ${renderFormSection({
        title: "Identity",
        body: `
              <label class="field">
                <span>Name</span>
                <input name="name" required placeholder="sdk-openai" />
              </label>
            `,
    })}
          ${renderFormSection({
        title: "Scope limits",
        body: `
              <div class="triple-grid">
                <label class="field">
                  <span>Providers</span>
                  <input name="providers" placeholder="openai, anthropic" />
                </label>
                <label class="field">
                  <span>Endpoints</span>
                  <input name="endpoints" placeholder="chat/completions, responses" />
                </label>
                <label class="field">
                  <span>Models</span>
                  <input name="models" placeholder="GigaChat-2-Max" />
                </label>
              </div>
            `,
    })}
          <div class="form-actions">
            <button class="button" type="submit">Create scoped key</button>
            <span class="muted">The full key value is shown once after creation or rotation.</span>
          </div>
        </form>
      `, "panel panel--span-8 panel--measure")}
    ${card("Current posture and handoff", `
        <div class="stack">
          ${renderDefinitionList([
        {
            label: "Global preview",
            value: String(global.key_preview ?? "not configured"),
            note: global.configured
                ? "Keep this for controlled broad access or emergency recovery only."
                : "No broad fallback is configured right now.",
        },
        {
            label: "Best smoke path",
            value: global.configured || scoped.length ? "Playground" : "Setup / Security",
            note: global.configured || scoped.length
                ? "Copy the desired key into the left-rail gateway field before the next smoke run."
                : "Security bootstrap or key creation still needs to happen before smoke traffic makes sense.",
        },
        {
            label: "Usage confirmation",
            value: totalRequestCount ? "Traffic usage is warm" : "Traffic usage is idle",
            note: "Usage traffic remains the confirmation surface after one request lands.",
        },
    ], "Current key posture is unavailable.")}
          <div class="toolbar">
            <a class="button button--secondary" href="${escapeHtml(pathForPage("settings-security"))}">Security settings</a>
            <a class="button button--secondary" href="${escapeHtml(pathForPage("traffic-usage"))}">Usage traffic</a>
          </div>
        </div>
      `, "panel panel--span-4 panel--aside")}
    ${card("Scoped key inventory", renderTable([
        { label: "Name" },
        { label: "Scope posture" },
        { label: "Usage" },
        { label: "Preview" },
        { label: "Actions" },
    ], scoped.map((item) => {
        const name = String(item.name ?? "");
        return [
            `<strong>${escapeHtml(name)}</strong>`,
            `<span class="muted">${escapeHtml(describeScopePosture(item))}</span>`,
            `<span class="muted">${escapeHtml(describeUsage(asRecord(item.usage)))}</span>`,
            `<span class="muted">${escapeHtml(String(item.key_preview ?? ""))}</span>`,
            `
              <div class="toolbar">
                <button class="button button--secondary" data-rotate="${escapeHtml(name)}" type="button">Rotate</button>
                <button class="button button--danger" data-delete="${escapeHtml(name)}" type="button">Delete</button>
              </div>
            `,
        ];
    }), "No scoped keys yet. Create one above to establish a narrower handoff than the global key."), "panel panel--span-8 panel--measure")}
    ${card("Guide and troubleshooting", renderGuideLinks([
        {
            label: "Overview workflow guide",
            href: OPERATOR_GUIDE_LINKS.overview,
            note: "Use the broader operator map when the question is really about where key management sits relative to Setup, Playground, or runtime diagnostics.",
        },
        {
            label: "Troubleshooting handoff map",
            href: OPERATOR_GUIDE_LINKS.troubleshooting,
            note: "Open the escalation map when key posture looks correct but request failures still need a different surface.",
        },
        {
            label: "Provider surface diagnostics",
            href: OPERATOR_GUIDE_LINKS.providers,
            note: "Use provider diagnostics only after a key works but the mounted compatibility surface still behaves differently than expected.",
        },
    ], {
        compact: true,
        collapsibleSummary: "Operator guides",
        intro: "Keys stay narrow on purpose.",
    }), "panel panel--span-4 panel--aside")}
    ${card("Current key snapshot", `
        <details class="details-disclosure">
          <summary>Current key snapshot</summary>
          <p class="field-note">
            Raw usage and preview metadata stay secondary. Open this only when the executive summary and inventory rows still leave ambiguity.
          </p>
          ${renderJson(keys)}
        </details>
      `, "panel panel--span-12")}
  `);
    const rotateButton = document.getElementById("rotate-global-key");
    rotateButton?.addEventListener("click", async () => {
        const response = await app.api.json("/admin/api/keys/global/rotate", {
            method: "POST",
            json: {},
        });
        const nextGlobal = asRecord(response.global);
        app.saveAdminKey(String(nextGlobal.value ?? ""));
        app.saveGatewayKey(String(nextGlobal.value ?? ""));
        app.queueAlert(`Global key rotated. New value: ${String(nextGlobal.value ?? "")}`, "warn");
        await app.render("keys");
    });
    const scopedForm = app.pageContent.querySelector("#scoped-key-form");
    scopedForm?.addEventListener("submit", async (event) => {
        event.preventDefault();
        const form = event.currentTarget;
        const fields = form.elements;
        const response = await app.api.json("/admin/api/keys/scoped", {
            method: "POST",
            json: {
                name: fields.name.value.trim(),
                providers: parseCsv(fields.providers.value),
                endpoints: parseCsv(fields.endpoints.value),
                models: parseCsv(fields.models.value),
            },
        });
        const scopedKey = asRecord(response.scoped_key);
        app.queueAlert(`Scoped key created. Value: ${String(scopedKey.value ?? "")}`, "warn");
        await app.render("keys");
    });
    app.pageContent.querySelectorAll("[data-rotate]").forEach((button) => {
        button.addEventListener("click", async () => {
            const name = button.dataset.rotate;
            if (!name) {
                return;
            }
            const response = await app.api.json(`/admin/api/keys/scoped/${encodeURIComponent(name)}/rotate`, {
                method: "POST",
                json: {},
            });
            const scopedKey = asRecord(response.scoped_key);
            app.queueAlert(`Scoped key ${name} rotated. New value: ${String(scopedKey.value ?? "")}`, "warn");
            await app.render("keys");
        });
    });
    app.pageContent.querySelectorAll("[data-delete]").forEach((button) => {
        button.addEventListener("click", async () => {
            const name = button.dataset.delete;
            if (!name) {
                return;
            }
            await app.api.json(`/admin/api/keys/scoped/${encodeURIComponent(name)}`, {
                method: "DELETE",
            });
            app.queueAlert(`Scoped key ${name} deleted.`, "info");
            await app.render("keys");
        });
    });
}
function renderKeysBanner(global, scoped) {
    if (!global.configured && scoped.length === 0) {
        return banner("No reusable gateway credentials are configured yet. Create a global or scoped key before handing the proxy to external SDKs or operators.", "warn");
    }
    if (!global.configured) {
        return banner("Only scoped keys are configured right now. That is acceptable for narrow clients, but emergency operator recovery may still want a deliberate global fallback.", "info");
    }
    if (scoped.length === 0) {
        return banner("A broad global key exists, but there are no client-specific scoped keys yet. Create one before distributing access beyond a single operator path.", "warn");
    }
    return banner("Global fallback and scoped client keys are both present. Keep distribution narrow, then confirm attribution from Traffic > Usage after one smoke request.", "info");
}
function describeScopePosture(item) {
    const parts = [
        csv(item.providers) ? `providers: ${csv(item.providers)}` : "",
        csv(item.endpoints) ? `endpoints: ${csv(item.endpoints)}` : "",
        csv(item.models) ? `models: ${csv(item.models)}` : "",
    ].filter(Boolean);
    return parts.join(" · ") || "full scoped access";
}
function describeUsage(usage) {
    const requests = readUsageCount(usage.request_count);
    const totalTokens = readUsageCount(usage.total_tokens);
    if (requests === 0 && totalTokens === 0) {
        return "No attributed usage yet";
    }
    return `${formatNumber(requests)} requests · ${formatNumber(totalTokens)} tokens`;
}
function hasScopedRestrictions(item) {
    return Boolean(csv(item.providers) || csv(item.endpoints) || csv(item.models));
}
function countKeysWithUsage(global, scoped) {
    return [
        readUsageCount(asRecord(global.usage).request_count) > 0,
        ...scoped.map((item) => readUsageCount(asRecord(item.usage).request_count) > 0),
    ].filter(Boolean).length;
}
function readUsageCount(value) {
    const normalized = Number(value ?? 0);
    return Number.isFinite(normalized) ? normalized : 0;
}
