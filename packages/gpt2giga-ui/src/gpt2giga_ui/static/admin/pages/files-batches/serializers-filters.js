import { safeJsonParse, setQueryParamIfPresent, } from "../../utils.js";
import { DEFAULT_FILE_SORT } from "./state.js";
export function readFilesBatchesFilters() {
    const params = new URLSearchParams(window.location.search);
    return scopeFilesBatchesFilters("files-batches", {
        query: params.get("query") || "",
        purpose: params.get("purpose") || "",
        batchStatus: params.get("batch_status") || "",
        endpoint: params.get("endpoint") || "",
        fileSort: parseFileSort(params.get("file_sort")),
    });
}
export function readFilesBatchesFiltersForPage(page) {
    const params = new URLSearchParams(window.location.search);
    return scopeFilesBatchesFilters(page, {
        query: params.get("query") || "",
        purpose: params.get("purpose") || "",
        batchStatus: params.get("batch_status") || "",
        endpoint: params.get("endpoint") || "",
        fileSort: parseFileSort(params.get("file_sort")),
    });
}
export function readFilesBatchesRouteState(page = "files-batches") {
    const params = new URLSearchParams(window.location.search);
    return scopeFilesBatchesRouteState(page, {
        selectedFileId: params.get("selected_file") || "",
        selectedBatchId: params.get("selected_batch") || "",
        composeInputFileId: params.get("compose_input") || "",
    });
}
export function buildFilesBatchesUrl(filters, routeState, page = "files-batches") {
    const scopedPage = isFilesBatchesPage(page) ? page : "files-batches";
    const scopedFilters = scopeFilesBatchesFilters(scopedPage, filters);
    const scopedRouteState = scopeFilesBatchesRouteState(scopedPage, routeState);
    const params = new URLSearchParams();
    setQueryParamIfPresent(params, "query", scopedFilters.query);
    setQueryParamIfPresent(params, "purpose", scopedFilters.purpose);
    setQueryParamIfPresent(params, "batch_status", scopedFilters.batchStatus);
    setQueryParamIfPresent(params, "endpoint", scopedFilters.endpoint);
    setQueryParamIfPresent(params, "file_sort", scopedFilters.fileSort === DEFAULT_FILE_SORT ? "" : scopedFilters.fileSort);
    setQueryParamIfPresent(params, "selected_file", scopedRouteState.selectedFileId);
    setQueryParamIfPresent(params, "selected_batch", scopedRouteState.selectedBatchId);
    setQueryParamIfPresent(params, "compose_input", scopedRouteState.composeInputFileId);
    const query = params.toString();
    const pathname = page === "overview" ? "/admin" : `/admin/${page}`;
    return query ? `${pathname}?${query}` : pathname;
}
export function scopeFilesBatchesFilters(page, filters) {
    return {
        query: filters.query,
        purpose: page === "batches" ? "" : filters.purpose,
        batchStatus: page === "files" ? "" : filters.batchStatus,
        endpoint: page === "files" ? "" : filters.endpoint,
        fileSort: page === "batches" ? DEFAULT_FILE_SORT : parseFileSort(filters.fileSort),
    };
}
export function scopeFilesBatchesRouteState(page, routeState) {
    return {
        selectedFileId: page === "batches" ? "" : routeState?.selectedFileId?.trim() ?? "",
        selectedBatchId: page === "files" ? "" : routeState?.selectedBatchId?.trim() ?? "",
        composeInputFileId: page === "files-batches" || page === "batches"
            ? routeState?.composeInputFileId?.trim() ?? ""
            : "",
    };
}
export function extractErrorReason(message) {
    const lines = String(message)
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean);
    if (!lines.length) {
        return "Unknown error";
    }
    const payloadText = lines.length > 1 ? lines.slice(1).join("\n") : lines[0];
    const payload = safeJsonParse(payloadText, null);
    const summary = summarizeErrorPayload(payload);
    if (summary) {
        return summary;
    }
    if (lines.length > 1) {
        return lines.slice(1).join(" ");
    }
    return lines[0];
}
function summarizeErrorPayload(payload) {
    if (typeof payload === "string") {
        return payload.trim();
    }
    if (typeof payload === "number" ||
        typeof payload === "boolean" ||
        typeof payload === "bigint") {
        return String(payload);
    }
    if (Array.isArray(payload)) {
        return payload
            .map((item) => summarizeErrorPayload(item))
            .filter(Boolean)
            .join("; ");
    }
    if (!payload || typeof payload !== "object") {
        return "";
    }
    const record = payload;
    const directMessage = typeof record.message === "string" ? record.message.trim() : "";
    if (directMessage) {
        return directMessage;
    }
    const validationMessage = summarizeValidationError(record);
    if (validationMessage) {
        return validationMessage;
    }
    for (const preferredKey of ["detail", "error"]) {
        const nestedSummary = summarizeErrorPayload(record[preferredKey]);
        if (nestedSummary) {
            return nestedSummary;
        }
    }
    const fieldSummaries = Object.entries(record)
        .filter(([key]) => key !== "url")
        .map(([key, value]) => {
        const entrySummary = summarizeErrorPayload(value);
        if (!entrySummary) {
            return "";
        }
        return `${key}: ${entrySummary}`;
    })
        .filter(Boolean);
    return fieldSummaries.join("; ");
}
function summarizeValidationError(record) {
    const message = typeof record.msg === "string" ? record.msg.trim() : "";
    if (!message) {
        return "";
    }
    const location = Array.isArray(record.loc)
        ? record.loc
            .map((part) => String(part ?? "").trim())
            .filter(Boolean)
            .join(".")
        : "";
    return location ? `${location}: ${message}` : message;
}
function isFilesBatchesPage(value) {
    return value === "files-batches" || value === "files" || value === "batches";
}
function parseFileSort(value) {
    switch (value) {
        case "created_asc":
        case "name_asc":
        case "name_desc":
        case "size_desc":
        case "size_asc":
            return value;
        case "created_desc":
        default:
            return DEFAULT_FILE_SORT;
    }
}
