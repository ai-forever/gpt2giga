import type { AdminApp } from "../app.js";
import { bindFilesBatchesPage } from "./files-batches/bindings.js";
import { loadFilesBatchesPageData } from "./files-batches/api.js";
import {
  buildFilesBatchesInventory,
  readFilesBatchesFilters,
} from "./files-batches/serializers.js";
import {
  renderFilesBatchesHeroActions,
  renderFilesBatchesPage,
  resolveFilesBatchesElements,
} from "./files-batches/view.js";

export async function renderFilesBatches(
  app: AdminApp,
  token: number,
): Promise<void> {
  const filters = readFilesBatchesFilters();
  const data = await loadFilesBatchesPageData(app);
  if (!app.isCurrentRender(token)) {
    return;
  }

  const inventory = buildFilesBatchesInventory(data, filters);
  app.setHeroActions(renderFilesBatchesHeroActions());
  app.setContent(renderFilesBatchesPage(data, inventory, filters));

  const elements = resolveFilesBatchesElements(app.pageContent);
  if (!elements) {
    return;
  }

  bindFilesBatchesPage({
    app,
    data,
    elements,
    filters,
    inventory,
  });
}
