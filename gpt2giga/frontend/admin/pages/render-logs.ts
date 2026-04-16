import type { AdminApp } from "../app.js";
import { bindLogsPage } from "./logs/bindings.js";
import { loadLogsPageData } from "./logs/api.js";
import { readLogsFilters } from "./logs/serializers.js";
import { renderLogsHeroActions, renderLogsPage, resolveLogsElements } from "./logs/view.js";

export async function renderLogs(app: AdminApp, token: number): Promise<void> {
  const filters = readLogsFilters();
  const data = await loadLogsPageData(app, filters);
  if (!app.isCurrentRender(token)) {
    return;
  }

  app.setHeroActions(renderLogsHeroActions());
  app.setContent(renderLogsPage(data, filters));

  const elements = resolveLogsElements(app.pageContent);
  if (!elements) {
    return;
  }

  bindLogsPage({
    app,
    data,
    elements,
    filters,
    token,
  });
}
