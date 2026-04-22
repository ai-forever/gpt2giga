import assert from "node:assert/strict";
import test from "node:test";

import type { FilesBatchesPageData } from "../../gpt2giga/frontend/admin/pages/files-batches/api.js";
import {
  buildFilesBatchesInventory,
  buildFilesBatchesUrl,
  describeFileValidationSnapshot,
  extractErrorReason,
  scopeFilesBatchesFilters,
  scopeFilesBatchesRouteState,
} from "../../gpt2giga/frontend/admin/pages/files-batches/serializers.js";
import type {
  FilesBatchesFilters,
  FilesBatchesRouteState,
} from "../../gpt2giga/frontend/admin/pages/files-batches/state.js";

function readSearchParams(url: string): URLSearchParams {
  return new URL(url, "http://localhost").searchParams;
}

const BASE_FILTERS: FilesBatchesFilters = {
  query: "",
  purpose: "",
  batchStatus: "",
  endpoint: "",
  fileSort: "created_desc",
};

test("scopeFilesBatchesFilters clears page-incompatible filters", () => {
  assert.deepEqual(
    scopeFilesBatchesFilters("batches", {
      ...BASE_FILTERS,
      purpose: "batch",
      batchStatus: "failed",
      endpoint: "/v1/responses",
      fileSort: "name_asc",
    }),
    {
      query: "",
      purpose: "",
      batchStatus: "failed",
      endpoint: "/v1/responses",
      fileSort: "created_desc",
    },
  );
});

test("scopeFilesBatchesRouteState trims ids and drops unsupported state", () => {
  const routeState: Partial<FilesBatchesRouteState> = {
    selectedFileId: " file-1 ",
    selectedBatchId: " batch-1 ",
    composeInputFileId: " input-7 ",
  };

  assert.deepEqual(scopeFilesBatchesRouteState("files", routeState), {
    selectedFileId: "file-1",
    selectedBatchId: "",
    composeInputFileId: "",
  });
});

test("buildFilesBatchesUrl scopes filters and route state by page", () => {
  const url = buildFilesBatchesUrl(
    {
      ...BASE_FILTERS,
      query: "invoice",
      purpose: "batch",
      batchStatus: "completed",
      endpoint: "/v1/responses",
      fileSort: "name_asc",
    },
    {
      selectedFileId: "file-1",
      selectedBatchId: "batch-9",
      composeInputFileId: "input-3",
    },
    "files",
  );

  assert.equal(new URL(url, "http://localhost").pathname, "/admin/files");
  const params = readSearchParams(url);
  assert.equal(params.get("query"), "invoice");
  assert.equal(params.get("purpose"), "batch");
  assert.equal(params.get("file_sort"), "name_asc");
  assert.equal(params.get("selected_file"), "file-1");
  assert.equal(params.has("batch_status"), false);
  assert.equal(params.has("endpoint"), false);
  assert.equal(params.has("selected_batch"), false);
  assert.equal(params.has("compose_input"), false);
});

test("buildFilesBatchesInventory keeps sorted file order and summary counts", () => {
  const data: FilesBatchesPageData = {
    inventoryPayload: {
      files: [],
      batches: [],
      counts: { files: 0, batches: 0, output_ready: 0, needs_attention: 0 },
    },
    files: [
      { id: "file-b", api_format: "openai", filename: "beta.jsonl", purpose: "batch" },
      { id: "file-a", api_format: "openai", filename: "alpha.jsonl", purpose: "batch" },
    ],
    batches: [
      { id: "batch-1", api_format: "openai", input_file_id: "file-a", status: "failed" },
      {
        id: "batch-2",
        api_format: "openai",
        input_file_id: "file-b",
        output_file_id: "file-out",
        status: "completed",
      },
    ],
    counts: { files: 2, batches: 2, output_ready: 1, needs_attention: 1 },
  };

  const inventory = buildFilesBatchesInventory(data, {
    ...BASE_FILTERS,
    purpose: "batch",
    fileSort: "name_asc",
  });

  assert.deepEqual(
    inventory.filteredFiles.map((item) => item.id),
    ["file-a", "file-b"],
  );
  assert.equal(inventory.attentionBatches, 1);
  assert.equal(inventory.outputReadyBatches, 1);
  assert.equal(inventory.fileLookup.get("file-a")?.filename, "alpha.jsonl");
  assert.equal(inventory.batchLookup.get("batch-2")?.output_file_id, "file-out");
});

test("extractErrorReason unwraps nested validation payloads", () => {
  const message = [
    "Upstream validation failed",
    JSON.stringify({
      detail: [{ loc: ["body", "messages", 0], msg: "field required" }],
    }),
  ].join("\n");

  assert.equal(extractErrorReason(message), "body.messages.0: field required");
});

test("describeFileValidationSnapshot reports blocking validation state", () => {
  assert.deepEqual(
    describeFileValidationSnapshot({
      status: "invalid",
      total_rows: 12,
      error_count: 3,
      warning_count: 1,
      detected_format: "openai",
    }),
    {
      label: "Invalid",
      tone: "warn",
      note: "12 rows · 3 errors · 1 warnings. Fix blocking issues before creating the batch.",
    },
  );
});
