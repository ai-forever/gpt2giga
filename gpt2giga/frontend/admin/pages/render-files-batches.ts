import type { AdminApp } from "../app.js";
import { subpagesFor } from "../routes.js";
import { card, renderSubpageNav } from "../templates.js";
import { bindFilesBatchesPage } from "./files-batches/bindings.js";
import {
  clearFilesBatchesPageDataCache,
  loadFilesBatchesPageData,
} from "./files-batches/api.js";
import {
  buildFilesBatchesInventory,
  buildFilesBatchesUrl,
  readFilesBatchesFiltersForPage,
} from "./files-batches/serializers.js";
import { DEFAULT_FILE_SORT } from "./files-batches/state.js";
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
  const filters = readFilesBatchesFiltersForPage(page);
  const data = await loadFilesBatchesPageData(app);
  if (!app.isCurrentRender(token)) {
    return;
  }

  const inventory = buildFilesBatchesInventory(data, filters);
  app.setHeroActions(renderFilesBatchesHeroActions(page));
  app.setContent(`
    ${card(
      "Workbench navigation",
      renderSubpageNav({
        currentPage: page,
        title: "Files & batches pages",
        intro:
          page === "files-batches"
            ? "Use the hub for counts only. Open files or batches for real work."
            : page === "files"
              ? "Keep this page file-first: upload, inspect, preview."
              : "Keep this page batch-first: create jobs, inspect lifecycle, preview outputs.",
        items: subpagesFor(page),
      }),
      "panel panel--span-12",
    )}
    ${renderFilesBatchesPage(page, data, inventory, filters)}
  `);

  document.getElementById("refresh-files-batches")?.addEventListener("click", () => {
    clearFilesBatchesPageDataCache();
    void app.render(page);
  });
  document
    .getElementById("reset-files-batches-filters")
    ?.addEventListener("click", () => {
      window.history.replaceState(
        {},
        "",
        buildFilesBatchesUrl(
          {
            query: "",
            purpose: "",
            batchStatus: "",
            endpoint: "",
            fileSort: DEFAULT_FILE_SORT,
          },
          undefined,
          page,
        ),
      );
      void app.render(page);
    });

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
