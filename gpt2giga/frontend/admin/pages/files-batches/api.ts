import type { AdminApp } from "../../app.js";
import type { BatchRecord, FileRecord } from "./state.js";

interface FilesBatchesInventoryCounts {
  files: number;
  batches: number;
  output_ready: number;
  needs_attention: number;
}

interface FilesBatchesInventoryPayload {
  files: FileRecord[];
  batches: BatchRecord[];
  counts: FilesBatchesInventoryCounts;
}

export interface FilesBatchesPageData {
  inventoryPayload: FilesBatchesInventoryPayload;
  files: FileRecord[];
  batches: BatchRecord[];
  counts: FilesBatchesInventoryCounts;
}

export async function loadFilesBatchesPageData(
  app: AdminApp,
): Promise<FilesBatchesPageData> {
  const inventoryPayload = await app.api.json<FilesBatchesInventoryPayload>(
    "/admin/api/files-batches/inventory",
    {},
    true,
  );

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

export async function fetchFileMetadata(
  app: AdminApp,
  fileId: string,
): Promise<FileRecord> {
  return app.api.json<FileRecord>(
    `/admin/api/files-batches/files/${encodeURIComponent(fileId)}`,
    {},
    true,
  );
}

export async function fetchBatchMetadata(
  app: AdminApp,
  batchId: string,
): Promise<BatchRecord> {
  return app.api.json<BatchRecord>(
    `/admin/api/files-batches/batches/${encodeURIComponent(batchId)}`,
    {},
    true,
  );
}

export async function fetchFileContent(
  app: AdminApp,
  fileId: string,
  contentPath?: string | null,
): Promise<Uint8Array> {
  const normalizedContentPath = contentPath?.trim();
  const response = await app.api.raw(
    normalizedContentPath ||
      `/v1/files/${encodeURIComponent(fileId)}/content`,
    {},
    true,
  );
  return new Uint8Array(await response.arrayBuffer());
}

export async function uploadFile(
  app: AdminApp,
  payload: {
    apiFormat: "openai" | "anthropic" | "gemini";
    purpose: string;
    file: File;
    displayName?: string;
  },
): Promise<FileRecord> {
  const body = new FormData();
  body.set("api_format", payload.apiFormat);
  body.set("purpose", payload.purpose);
  if (payload.displayName?.trim()) {
    body.set("display_name", payload.displayName.trim());
  }
  body.set("file", payload.file, payload.file.name);
  return app.api.json<FileRecord>(
    "/admin/api/files-batches/files",
    { method: "POST", body },
    true,
  );
}

export async function createBatch(
  app: AdminApp,
  payload: {
    apiFormat: "openai" | "anthropic" | "gemini";
    endpoint?: string;
    inputFileId?: string;
    metadata?: Record<string, unknown>;
    displayName?: string;
    model?: string;
    requests?: Array<Record<string, unknown>>;
  },
): Promise<BatchRecord> {
  return app.api.json<BatchRecord>(
    "/admin/api/files-batches/batches",
    {
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
    },
    true,
  );
}

export async function deleteFile(
  app: AdminApp,
  fileId: string,
  deletePath?: string | null,
): Promise<void> {
  const normalizedDeletePath = deletePath?.trim();
  await app.api.json(
    normalizedDeletePath || `/v1/files/${encodeURIComponent(fileId)}`,
    { method: "DELETE" },
    true,
  );
}
