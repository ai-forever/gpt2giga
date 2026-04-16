import type { AdminApp } from "../app.js";
import { subpagesFor } from "../routes.js";
import { card, renderSubpageNav } from "../templates.js";
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
  const currentPage = app.currentPage();
  const page =
    currentPage === "files" || currentPage === "batches" ? currentPage : "files-batches";
  const filters = readFilesBatchesFilters();
  const data = await loadFilesBatchesPageData(app);
  if (!app.isCurrentRender(token)) {
    return;
  }

  const inventory = buildFilesBatchesInventory(data, filters);
  app.setHeroActions(renderFilesBatchesHeroActions());
  app.setContent(`
    ${card(
      "Workbench navigation",
      renderSubpageNav({
        currentPage: page,
        title: "Files & batches pages",
        intro:
          page === "files-batches"
            ? "The focused files and batches pages are wired up as dedicated URLs. This slice keeps the shared workbench available while the split continues."
            : "This URL is ready for the files and batches split. The deeper layout refactor will narrow the page further in the next slice.",
        items: subpagesFor(page),
      }),
      "panel panel--span-12",
    )}
    ${renderFilesBatchesPage(data, inventory, filters)}
  `);

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
    page,
  });
}
