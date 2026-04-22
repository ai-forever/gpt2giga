import { bindSettingsPage } from "./settings/bindings.js";
import { buildSettingsPageState } from "./settings/state.js";
import { renderSettingsContent } from "./settings/view.js";
export async function renderSettings(app, token) {
    await renderSettingsPage(app, token, "settings");
}
export async function renderSettingsApplication(app, token) {
    await renderSettingsPage(app, token, "settings-application");
}
export async function renderSettingsObservability(app, token) {
    await renderSettingsPage(app, token, "settings-observability");
}
export async function renderSettingsGigachat(app, token) {
    await renderSettingsPage(app, token, "settings-gigachat");
}
export async function renderSettingsSecurity(app, token) {
    await renderSettingsPage(app, token, "settings-security");
}
export async function renderSettingsHistory(app, token) {
    await renderSettingsPage(app, token, "settings-history");
}
async function renderSettingsPage(app, token, currentPage) {
    const [application, observability, gigachat, security, revisionsPayload] = await Promise.all([
        app.api.json("/admin/api/settings/application"),
        app.api.json("/admin/api/settings/observability"),
        app.api.json("/admin/api/settings/gigachat"),
        app.api.json("/admin/api/settings/security"),
        app.api.json("/admin/api/settings/revisions?limit=6"),
    ]);
    if (!app.isCurrentRender(token)) {
        return;
    }
    const state = buildSettingsPageState(currentPage, {
        application,
        observability,
        gigachat,
        security,
        revisionsPayload,
    });
    app.setHeroActions(`<button class="button button--secondary" id="reload-settings" type="button">Reload values</button>`);
    app.setContent(renderSettingsContent(state));
    document.getElementById("reload-settings")?.addEventListener("click", () => {
        void app.render(currentPage);
    });
    bindSettingsPage(app, state);
}
