import type { AdminApp } from "../app.js";
import { loadTrafficPageData } from "./traffic/api.js";
import { bindTrafficPage } from "./traffic/bindings.js";
import { readTrafficFilters } from "./traffic/serializers.js";
import {
  renderTrafficHeroActions,
  renderTrafficPage,
  resolveTrafficElements,
} from "./traffic/view.js";

export async function renderTraffic(app: AdminApp, token: number): Promise<void> {
  const filters = readTrafficFilters();
  const data = await loadTrafficPageData(app, filters);
  if (!app.isCurrentRender(token)) {
    return;
  }

  app.setHeroActions(renderTrafficHeroActions(filters));
  app.setContent(renderTrafficPage(data, filters));

  const elements = resolveTrafficElements(app.pageContent);
  if (!elements) {
    return;
  }

  bindTrafficPage({
    app,
    data,
    elements,
    filters,
  });
}
