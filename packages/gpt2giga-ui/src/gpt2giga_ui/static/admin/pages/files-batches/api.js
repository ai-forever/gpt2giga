import { asArray } from "../../utils.js";
export async function loadFilesBatchesPageData(app) {
    const [filesPayload, batchesPayload] = await Promise.all([
        app.api.json("/v1/files?order=desc&limit=100", {}, true),
        app.api.json("/v1/batches?limit=100", {}, true),
    ]);
    return {
        filesPayload,
        batchesPayload,
        files: asArray(filesPayload.data),
        batches: asArray(batchesPayload.data),
    };
}
export async function fetchFileMetadata(app, fileId) {
    return app.api.json(`/v1/files/${encodeURIComponent(fileId)}`, {}, true);
}
export async function fetchBatchMetadata(app, batchId) {
    return app.api.json(`/v1/batches/${encodeURIComponent(batchId)}`, {}, true);
}
export async function fetchFileContent(app, fileId) {
    const response = await app.api.raw(`/v1/files/${encodeURIComponent(fileId)}/content`, {}, true);
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
export async function deleteFile(app, fileId) {
    await app.api.json(`/v1/files/${encodeURIComponent(fileId)}`, { method: "DELETE" }, true);
}
