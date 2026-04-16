import type { AdminApp } from "../../app.js";
import { asArray } from "../../utils.js";
import type { BatchRecord, FileRecord } from "./state.js";

export interface FilesBatchesPageData {
  filesPayload: Record<string, unknown>;
  batchesPayload: Record<string, unknown>;
  files: FileRecord[];
  batches: BatchRecord[];
}

export async function loadFilesBatchesPageData(
  app: AdminApp,
): Promise<FilesBatchesPageData> {
  const [filesPayload, batchesPayload] = await Promise.all([
    app.api.json<Record<string, unknown>>("/v1/files?order=desc&limit=100", {}, true),
    app.api.json<Record<string, unknown>>("/v1/batches?limit=100", {}, true),
  ]);

  return {
    filesPayload,
    batchesPayload,
    files: asArray<FileRecord>(filesPayload.data),
    batches: asArray<BatchRecord>(batchesPayload.data),
  };
}

export async function fetchFileMetadata(
  app: AdminApp,
  fileId: string,
): Promise<Record<string, unknown>> {
  return app.api.json<Record<string, unknown>>(
    `/v1/files/${encodeURIComponent(fileId)}`,
    {},
    true,
  );
}

export async function fetchBatchMetadata(
  app: AdminApp,
  batchId: string,
): Promise<Record<string, unknown>> {
  return app.api.json<Record<string, unknown>>(
    `/v1/batches/${encodeURIComponent(batchId)}`,
    {},
    true,
  );
}

export async function fetchFileContent(
  app: AdminApp,
  fileId: string,
): Promise<Uint8Array> {
  const response = await app.api.raw(
    `/v1/files/${encodeURIComponent(fileId)}/content`,
    {},
    true,
  );
  return new Uint8Array(await response.arrayBuffer());
}

export async function uploadFile(
  app: AdminApp,
  purpose: string,
  file: File,
): Promise<Record<string, unknown>> {
  const body = new FormData();
  body.set("purpose", purpose);
  body.set("file", file, file.name);
  return app.api.json<Record<string, unknown>>(
    "/v1/files",
    { method: "POST", body },
    true,
  );
}

export async function createBatch(
  app: AdminApp,
  payload: {
    endpoint: string;
    inputFileId: string;
    metadata?: Record<string, unknown>;
  },
): Promise<Record<string, unknown>> {
  return app.api.json<Record<string, unknown>>(
    "/v1/batches",
    {
      method: "POST",
      json: {
        endpoint: payload.endpoint,
        input_file_id: payload.inputFileId,
        completion_window: "24h",
        metadata: payload.metadata,
      },
    },
    true,
  );
}

export async function deleteFile(app: AdminApp, fileId: string): Promise<void> {
  await app.api.json(`/v1/files/${encodeURIComponent(fileId)}`, { method: "DELETE" }, true);
}
