const FILES_BATCHES_CACHE_TTL_MS = 15_000;
let cachedFilesBatchesPageData = null;
function isAttentionBatchStatus(value) {
    const status = String(value ?? "").toLowerCase();
    return ["failed", "cancelled", "expired"].includes(status);
}
function buildInventoryCounts(data) {
    return {
        files: data.files.length,
        batches: data.batches.length,
        output_ready: data.batches.filter((item) => Boolean(String(item.output_file_id ?? ""))).length,
        needs_attention: data.batches.filter((item) => isAttentionBatchStatus(item.status)).length,
    };
}
function buildPageData(inventoryPayload) {
    return {
        inventoryPayload,
        files: inventoryPayload.files ?? [],
        batches: inventoryPayload.batches ?? [],
        counts: inventoryPayload.counts ?? {
            files: 0,
            batches: 0,
            output_ready: 0,
            needs_attention: 0,
        },
    };
}
function hasFreshCache() {
    return (cachedFilesBatchesPageData !== null &&
        Date.now() - cachedFilesBatchesPageData.cachedAt <= FILES_BATCHES_CACHE_TTL_MS);
}
export function clearFilesBatchesPageDataCache() {
    cachedFilesBatchesPageData = null;
}
export function syncFilesBatchesPageDataCache(data) {
    const counts = buildInventoryCounts(data);
    data.counts = counts;
    data.inventoryPayload = {
        files: data.files,
        batches: data.batches,
        counts,
    };
    cachedFilesBatchesPageData = {
        cachedAt: Date.now(),
        data,
    };
    return data;
}
export async function loadFilesBatchesPageData(app) {
    if (hasFreshCache()) {
        return cachedFilesBatchesPageData.data;
    }
    const inventoryPayload = await app.api.json("/admin/api/files-batches/inventory", {}, true);
    return syncFilesBatchesPageDataCache(buildPageData(inventoryPayload));
}
export async function fetchFileMetadata(app, fileId) {
    return app.api.json(`/admin/api/files-batches/files/${encodeURIComponent(fileId)}`, {}, true);
}
export async function fetchBatchMetadata(app, batchId) {
    return app.api.json(`/admin/api/files-batches/batches/${encodeURIComponent(batchId)}`, {}, true);
}
export async function fetchFileContent(app, fileId, contentPath) {
    const normalizedContentPath = contentPath?.trim();
    const response = await app.api.raw(normalizedContentPath ||
        `/v1/files/${encodeURIComponent(fileId)}/content`, {}, true);
    return new Uint8Array(await response.arrayBuffer());
}
export async function uploadFile(app, payload) {
    const body = new FormData();
    body.set("api_format", payload.apiFormat);
    body.set("purpose", payload.purpose);
    if (payload.displayName?.trim()) {
        body.set("display_name", payload.displayName.trim());
    }
    body.set("file", payload.file, payload.file.name);
    return app.api.json("/admin/api/files-batches/files", { method: "POST", body }, true);
}
export async function createBatch(app, payload) {
    return app.api.json("/admin/api/files-batches/batches", {
        method: "POST",
        json: {
            api_format: payload.apiFormat,
            endpoint: payload.endpoint,
            input_file_id: payload.inputFileId,
            metadata: payload.metadata,
            display_name: payload.displayName,
            model: payload.model,
            requests: payload.requests,
        },
    }, true);
}
export async function deleteFile(app, fileId, deletePath) {
    const normalizedDeletePath = deletePath?.trim();
    await app.api.json(normalizedDeletePath || `/v1/files/${encodeURIComponent(fileId)}`, { method: "DELETE" }, true);
}
