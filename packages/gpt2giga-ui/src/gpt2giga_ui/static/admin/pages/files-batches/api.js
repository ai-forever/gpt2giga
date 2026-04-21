export async function loadFilesBatchesPageData(app) {
    const inventoryPayload = await app.api.json("/admin/api/files-batches/inventory", {}, true);
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
export async function uploadFile(app, purpose, file) {
    const body = new FormData();
    body.set("purpose", purpose);
    body.set("file", file, file.name);
    return app.api.json("/v1/files", { method: "POST", body }, true);
}
export async function createBatch(app, payload) {
    return app.api.json("/v1/batches", {
        method: "POST",
        json: {
            endpoint: payload.endpoint,
            input_file_id: payload.inputFileId,
            completion_window: "24h",
            metadata: payload.metadata,
        },
    }, true);
}
export async function deleteFile(app, fileId, deletePath) {
    const normalizedDeletePath = deletePath?.trim();
    await app.api.json(normalizedDeletePath || `/v1/files/${encodeURIComponent(fileId)}`, { method: "DELETE" }, true);
}
