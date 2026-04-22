import type { AdminApp } from "../../../app.js";
import { buildFilesBatchesUrl } from "../serializers.js";
import type {
  FilesBatchesFilters,
  FilesBatchesPage,
} from "../state.js";
import type { FilesBatchesPageElements } from "../view.js";

interface BindFilesBatchesFiltersOptions {
  app: AdminApp;
  elements: FilesBatchesPageElements;
  filters: FilesBatchesFilters;
  page: FilesBatchesPage;
}

export function bindFilesBatchesFilters(
  options: BindFilesBatchesFiltersOptions,
): void {
  const { app, elements, filters, page } = options;

  elements.filtersForm?.addEventListener("submit", (event) => {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    const fields = form.elements as typeof form.elements & {
      query?: HTMLInputElement;
      purpose?: HTMLSelectElement;
      batch_status?: HTMLSelectElement;
      endpoint?: HTMLSelectElement;
      file_sort?: HTMLSelectElement;
    };

    const nextFilters: FilesBatchesFilters = {
      query: fields.query?.value.trim() ?? "",
      purpose: fields.purpose?.value ?? "",
      batchStatus: fields.batch_status?.value ?? "",
      endpoint: fields.endpoint?.value ?? "",
      fileSort:
        (fields.file_sort?.value as FilesBatchesFilters["fileSort"] | undefined) ??
        filters.fileSort,
    };
    window.history.replaceState(
      {},
      "",
      buildFilesBatchesUrl(nextFilters, undefined, page),
    );
    void app.render(page);
  });
}
