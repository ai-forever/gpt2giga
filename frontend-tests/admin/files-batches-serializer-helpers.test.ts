import assert from "node:assert/strict";
import test from "node:test";

import { renderInspectorActions } from "../../gpt2giga/frontend/admin/pages/files-batches/serializers-inventory.js";
import {
  buildContentPreviewSummary,
  buildFilePreview,
} from "../../gpt2giga/frontend/admin/pages/files-batches/serializers-preview.js";
import type {
  BatchRecord,
  InspectorSelection,
} from "../../gpt2giga/frontend/admin/pages/files-batches/state.js";

test("renderInspectorActions exposes scoped traffic and logs handoff for batch output", () => {
  const selection: InspectorSelection = {
    kind: "batch",
    batchId: "batch-7",
    inputFileId: "file-input",
    outputFileId: "file-output",
    handoffRequestId: "req-42",
    handoffRequestCount: 3,
  };
  const batches = new Map<string, BatchRecord>([
    [
      "batch-7",
      {
        id: "batch-7",
        status: "completed",
        output_file_id: "file-output",
      },
    ],
  ]);

  const markup = renderInspectorActions("batches", selection, new Map(), batches, []);

  assert.match(markup, /Open traffic for sample result/);
  assert.match(markup, /href="\/admin\/traffic\?request_id=req-42"/);
  assert.match(markup, /href="\/admin\/logs\?request_id=req-42"/);
  assert.match(markup, /scoped Traffic\/Logs handoff is ready from sample request req-42/);
});

test("buildFilePreview detects batch output request handoff metadata", () => {
  const payload = [
    JSON.stringify({
      custom_id: "result-1",
      response: { request_id: "req-1" },
    }),
    JSON.stringify({
      custom_id: "result-2",
      response: { request_id: "req-2" },
      error: { message: "failed" },
    }),
  ].join("\n");
  const preview = buildFilePreview(new TextEncoder().encode(payload), "batch-output.jsonl");
  const summary = buildContentPreviewSummary(preview, "file-output", "Batch output");

  assert.equal(preview.kind, "text");
  assert.equal(preview.contentKind, "Batch output");
  assert.equal(preview.handoffRequestId, "req-1");
  assert.equal(preview.handoffRequestCount, 2);
  assert.deepEqual(summary.at(-1), {
    label: "Downstream handoff",
    value: "Sample request scoped",
    note: "Traffic and Logs can open with sample request req-1 from 2 decoded result rows.",
  });
});
