import assert from "node:assert/strict";
import test from "node:test";

import {
  buildBatchValidationRequest,
  readBatchApiFormatValue,
  resolveBatchEndpointValue,
  resolveComposerDisplayName,
  resolveDisplayedFileValidationSnapshot,
} from "../../gpt2giga/frontend/admin/pages/files-batches/bindings/batch-composer-state.js";
import {
  buildFileSelectionSurface,
  resolveContentPathForFile,
} from "../../gpt2giga/frontend/admin/pages/files-batches/bindings/inventory-selection.js";
import type {
  BatchRecord,
  FileRecord,
  FileValidationSnapshot,
} from "../../gpt2giga/frontend/admin/pages/files-batches/state.js";

test("resolveContentPathForFile prefers linked batch output path over file content path", () => {
  const source: FileRecord = {
    id: "file-output",
    filename: "output.jsonl",
    content_path: "/files/file-output/content",
  };
  const batch: BatchRecord = {
    id: "batch-1",
    output_file_id: "file-output",
    output_path: "/batches/batch-1/output",
  };

  assert.equal(
    resolveContentPathForFile({
      fileId: "file-output",
      source,
      relatedBatch: batch,
      batches: [batch],
    }),
    "/batches/batch-1/output",
  );
});

test("buildFileSelectionSurface reports composer handoff validation details", () => {
  const validationSnapshot: FileValidationSnapshot = {
    status: "valid_with_warnings",
    total_rows: 3,
    error_count: 0,
    warning_count: 2,
    detected_format: "gemini",
    validated_at: 1234,
  };

  const surface = buildFileSelectionSurface({
    fileId: "file-input",
    source: {
      id: "file-input",
      filename: "input.jsonl",
      purpose: "batch",
      api_format: "gemini",
    },
    mode: "composer",
    detailPayload: "Selected file-input as batch input.",
    batches: [],
    validationSnapshot,
  });

  assert.equal(surface.detailTitle, "Composer handoff");
  assert.equal(surface.detailOpen, false);
  assert.deepEqual(surface.summary.at(0), {
    label: "Selection",
    value: "Batch input ready",
  });
  assert.match(
    String(surface.detailItems.find((item) => item.label === "Validation")?.value),
    /Warnings/i,
  );
});

test("readBatchApiFormatValue falls back to openai for unknown values", () => {
  assert.equal(readBatchApiFormatValue("anthropic"), "anthropic");
  assert.equal(readBatchApiFormatValue("other"), "openai");
});

test("resolveBatchEndpointValue keeps provider-specific endpoints canonical", () => {
  assert.equal(
    resolveBatchEndpointValue({
      apiFormat: "gemini",
      selectedEndpoint: "/ignored",
      batchModel: "models/gemini-2.5-flash:generateContent",
      fallbackModel: "gemini-2.5-pro",
    }),
    "/v1beta/models/gemini-2.5-flash:generateContent",
  );
  assert.equal(
    resolveBatchEndpointValue({
      apiFormat: "openai",
      selectedEndpoint: "/invalid",
      batchModel: "",
      fallbackModel: "gpt-4.1",
    }),
    "/v1/chat/completions",
  );
});

test("buildBatchValidationRequest prioritizes inline requests over staged file ids", () => {
  const request = buildBatchValidationRequest({
    apiFormat: "openai",
    endpoint: "/v1/responses",
    inputFileId: "file-1",
    fallbackModel: "gpt-4.1",
    inlinePayload: {
      provided: true,
      requests: [{ custom_id: "req-1", body: { model: "gpt-4.1" } }],
    },
  });

  assert.equal(request.sourceLabel, "1 inline request");
  assert.equal(request.inputFileId, undefined);
  assert.match(String(request.sourceNote), /override staged file file-1/i);
  assert.equal(request.requests?.length, 1);
});

test("resolveComposerDisplayName only autofills gemini batches", () => {
  assert.equal(
    resolveComposerDisplayName({
      apiFormat: "gemini",
      currentValue: "",
      inputFileId: "file-7",
    }),
    "gemini-file-7",
  );
  assert.equal(
    resolveComposerDisplayName({
      apiFormat: "openai",
      currentValue: "keep-me",
      inputFileId: "file-7",
    }),
    "",
  );
});

test("resolveDisplayedFileValidationSnapshot marks stored reports stale when inputs changed", () => {
  const source: FileRecord = {
    id: "file-1",
    purpose: "batch",
    validation: {
      status: "valid",
      total_rows: 4,
      error_count: 0,
      warning_count: 0,
      detected_format: "openai",
      validated_at: 10,
    },
  };

  const snapshot = resolveDisplayedFileValidationSnapshot({
    fileId: "file-1",
    source,
    currentRequest: {
      apiFormat: "openai",
      endpoint: "/v1/chat/completions",
      inputFileId: "file-1",
      sourceLabel: "Staged file file-1",
      signature: '{"file":"file-1"}',
    },
    state: {
      validationReport: null,
      validationDirty: true,
      validationSignature: '{"file":"old"}',
      validationValidatedAt: 20,
    },
  });

  assert.equal(snapshot?.status, "stale");
});
