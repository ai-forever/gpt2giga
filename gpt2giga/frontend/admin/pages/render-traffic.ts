import type { AdminApp } from "../app";
import { card, renderJson } from "../templates";

export async function renderTraffic(app: AdminApp, token: number): Promise<void> {
  const [requests, errors, usageKeys, usageProviders] = await Promise.all([
    app.api.json<Record<string, unknown>>("/admin/api/requests/recent?limit=20"),
    app.api.json<Record<string, unknown>>("/admin/api/errors/recent?limit=20"),
    app.api.json<Record<string, unknown>>("/admin/api/usage/keys"),
    app.api.json<Record<string, unknown>>("/admin/api/usage/providers"),
  ]);

  if (!app.isCurrentRender(token)) {
    return;
  }

  app.setHeroActions(`<a class="button button--secondary" href="/admin/logs">Open logs</a>`);
  app.setContent(`
    ${card("Recent requests", renderJson(requests.events ?? []), "panel panel--span-6")}
    ${card("Recent errors", renderJson(errors.events ?? []), "panel panel--span-6")}
    ${card("Usage by key", renderJson(usageKeys.entries ?? []), "panel panel--span-6")}
    ${card("Usage by provider", renderJson(usageProviders.entries ?? []), "panel panel--span-6")}
  `);
}
