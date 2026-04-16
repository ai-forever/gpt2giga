import type { AdminApp } from "../app.js";
import { subpagesFor } from "../routes.js";
import { card, renderSubpageNav } from "../templates.js";
import { bindFilesBatchesPage } from "./files-batches/bindings.js";
import { loadFilesBatchesPageData } from "./files-batches/api.js";
import {
  buildFilesBatchesInventory,
  buildFilesBatchesUrl,
  readFilesBatchesFiltersForPage,
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
            ? "Use the hub for counts and handoff only. Open the dedicated files or batches page when the work stops being summary-first."
            : page === "files"
              ? "This page stays file-first: upload, inspect, preview, then hand off into the dedicated batch composer only when queueing is next."
              : "This page stays batch-first: create jobs, inspect lifecycle state, and preview outputs without file-upload noise.",
        items: subpagesFor(page),
      }),
      "panel panel--span-12",
    )}
    ${renderFilesBatchesPage(page, data, inventory, filters)}
  `);

  document.getElementById("refresh-files-batches")?.addEventListener("click", () => {
    void app.render(page);
  });
  document
    .getElementById("reset-files-batches-filters")
    ?.addEventListener("click", () => {
      window.history.replaceState(
        {},
        "",
        buildFilesBatchesUrl(
          { query: "", purpose: "", batchStatus: "", endpoint: "" },
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
