import type { AdminApp } from "../app";
import { card, renderJson } from "../templates";

export async function renderProviders(app: AdminApp, token: number): Promise<void> {
  const [capabilities, routes] = await Promise.all([
    app.api.json<Record<string, unknown>>("/admin/api/capabilities"),
    app.api.json<Record<string, unknown>>("/admin/api/routes"),
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
