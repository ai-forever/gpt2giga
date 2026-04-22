import { buildFilesBatchesUrl } from "../serializers.js";
export function bindFilesBatchesFilters(options) {
    const { app, elements, filters, page } = options;
    elements.filtersForm?.addEventListener("submit", (event) => {
        event.preventDefault();
        const form = event.currentTarget;
        const fields = form.elements;
        const nextFilters = {
            query: fields.query?.value.trim() ?? "",
            purpose: fields.purpose?.value ?? "",
            batchStatus: fields.batch_status?.value ?? "",
            endpoint: fields.endpoint?.value ?? "",
            fileSort: fields.file_sort?.value ??
                filters.fileSort,
        };
        window.history.replaceState({}, "", buildFilesBatchesUrl(nextFilters, undefined, page));
        void app.render(page);
    });
}
