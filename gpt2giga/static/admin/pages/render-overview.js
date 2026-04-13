import { card, kpi, renderJson } from "../templates";
import { asArray, asRecord } from "../utils";
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
    const summary = asRecord(usageProviders.summary);
    const recentErrors = asArray(errors.events)
        .slice(-5)
        .reverse();
    const enabledProviders = asArray(runtime.enabled_providers).join(", ") || "none";
    app.setHeroActions(setup.setup_complete
        ? `
          <a class="button" href="/admin/playground">Try playground</a>
          <a class="button button--secondary" href="/admin/settings">Open settings</a>
        `
        : `
          <a class="button" href="/admin/setup">Open setup wizard</a>
          <a class="button button--secondary" href="/admin/settings">Open settings</a>
        `);
    app.setContent([
        kpi("Requests", Number(summary.request_count ?? 0)),
        kpi("Errors", Number(summary.error_count ?? 0)),
        kpi("Tokens", Number(summary.total_tokens ?? 0)),
        kpi("Scoped Keys", Number(setup.scoped_api_keys_configured ?? 0)),
        card("Setup readiness", `
          <div class="stack">
            <div class="pill-row">
              <span class="pill">Persisted config: ${setup.persisted ? "yes" : "no"}</span>
              <span class="pill">GigaChat ready: ${setup.gigachat_ready ? "yes" : "no"}</span>
              <span class="pill">Security ready: ${setup.security_ready ? "yes" : "no"}</span>
              <span class="pill">Global key: ${setup.global_api_key_configured ? "configured" : "missing"}</span>
            </div>
          </div>
        `, "panel panel--span-4"),
        card("Runtime posture", `
          <div class="stack">
            <div class="pill-row">
              <span class="pill">Mode: ${runtime.mode ?? "n/a"}</span>
              <span class="pill">Providers: ${enabledProviders}</span>
              <span class="pill">Telemetry: ${runtime.telemetry_enabled ? "on" : "off"}</span>
              <span class="pill">Store: ${runtime.runtime_store_backend ?? "n/a"}</span>
            </div>
          </div>
        `, "panel panel--span-4"),
        card("Recent errors", recentErrors.length ? renderJson(recentErrors) : `<p>No recent errors recorded.</p>`, "panel panel--span-4"),
        card("Usage by key", renderJson(usageKeys.entries ?? []), "panel panel--span-6"),
        card("Usage by provider", renderJson(usageProviders.entries ?? []), "panel panel--span-6"),
    ].join(""));
}
