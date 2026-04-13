import { card, renderJson } from "../templates";
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
    app.setHeroActions(`<button class="button button--secondary" id="copy-diagnostics" type="button">Copy diagnostics JSON</button>`);
    app.setContent(`
    ${card("Setup", renderJson(setup), "panel panel--span-4")}
    ${card("Runtime", renderJson(runtime), "panel panel--span-4")}
    ${card("Config", renderJson(config), "panel panel--span-4")}
    ${card("Routes", renderJson(routes.routes ?? []), "panel panel--span-12")}
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
