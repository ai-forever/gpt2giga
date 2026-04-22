import assert from "node:assert/strict";
import test from "node:test";

import {
  buildBatchInlineRequestsTemplate,
  normalizeGeminiBatchModel,
  readInlineRequestsPayload,
  resolveValidationStatus,
} from "../../gpt2giga/frontend/admin/pages/files-batches/bindings/helpers.js";

test("normalizeGeminiBatchModel strips provider-specific prefixes and suffixes", () => {
  assert.equal(
    normalizeGeminiBatchModel(
      "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
    ),
    "gemini-2.5-flash",
  );
  assert.equal(
    normalizeGeminiBatchModel("models/gemini-2.0-flash-exp"),
    "gemini-2.0-flash-exp",
  );
});

test("readInlineRequestsPayload validates that inline requests stay arrays", () => {
  assert.deepEqual(readInlineRequestsPayload(""), { provided: false });
  assert.deepEqual(readInlineRequestsPayload('{"request":1}'), {
    provided: true,
    error: "Inline requests must be a JSON array.",
  });
  assert.deepEqual(readInlineRequestsPayload('[{"request":{"model":"giga"}}]'), {
    provided: true,
    requests: [{ request: { model: "giga" } }],
  });
});

test("buildBatchInlineRequestsTemplate keeps provider-specific request shapes", () => {
  const geminiTemplate = JSON.parse(
    buildBatchInlineRequestsTemplate({
      apiFormat: "gemini",
      fallbackModel: "gemini-2.5-flash",
      endpoint: "/ignored",
    }),
  ) as Array<Record<string, unknown>>;
  assert.equal(
    ((geminiTemplate[0].request as Record<string, unknown>).model as string),
    "models/gemini-2.5-flash",
  );

  const embeddingsTemplate = JSON.parse(
    buildBatchInlineRequestsTemplate({
      apiFormat: "openai",
      fallbackModel: "embeddings-model",
      endpoint: "/v1/embeddings",
    }),
  ) as Array<Record<string, unknown>>;
  assert.equal(embeddingsTemplate[0].url, "/v1/embeddings");
});

test("resolveValidationStatus prioritizes stale and blocking batch states", () => {
  assert.deepEqual(
    resolveValidationStatus({
      validationInFlight: true,
      validationDirty: false,
      validationReport: null,
    }),
    { label: "Validating", tone: "default" },
  );
  assert.deepEqual(
    resolveValidationStatus({
      validationInFlight: false,
      validationDirty: true,
      validationReport: {
        valid: true,
        api_format: "openai",
        summary: { total_rows: 3, error_count: 0, warning_count: 0 },
        issues: [],
      },
    }),
    { label: "Stale report", tone: "warn" },
  );
  assert.deepEqual(
    resolveValidationStatus({
      validationInFlight: false,
      validationDirty: false,
      validationReport: {
        valid: false,
        api_format: "openai",
        summary: { total_rows: 3, error_count: 1, warning_count: 0 },
        issues: [],
      },
    }),
    { label: "Invalid", tone: "warn" },
  );
});
