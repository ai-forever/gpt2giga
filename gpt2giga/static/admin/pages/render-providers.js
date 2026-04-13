import { card, renderJson } from "../templates";
export async function renderProviders(app, token) {
    const [capabilities, routes] = await Promise.all([
        app.api.json("/admin/api/capabilities"),
        app.api.json("/admin/api/routes"),
    ]);
    if (!app.isCurrentRender(token)) {
        return;
    }
    app.setHeroActions(`<a class="button button--secondary" href="/admin/system">Open system</a>`);
    app.setContent(`
    ${card("Capability matrix", renderJson(capabilities.matrix ?? {}), "panel panel--span-6")}
    ${card("Provider detail", renderJson(capabilities.providers ?? {}), "panel panel--span-6")}
    ${card("Mounted routes", renderJson(routes.routes ?? []), "panel panel--span-12")}
  `);
}
