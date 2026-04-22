import assert from "node:assert/strict";
import test from "node:test";

import {
  renderErrorPreviewRows,
  renderTrafficInspector,
  renderTrafficOverviewAside,
  renderUsagePreviewRows,
} from "../../gpt2giga/frontend/admin/pages/traffic/view-helpers.js";

test("renderTrafficInspector preserves ids and pinned request summary", () => {
  const markup = renderTrafficInspector({
    filters: {
      apiKeyName: "",
      endpoint: "",
      errorType: "",
      limit: "25",
      method: "",
      model: "",
      provider: "",
      requestId: "req-42",
      source: "",
      statusCode: "",
    },
    rawPayload: { request_id: "req-42" },
    statItems: [{ label: "Request rows", value: "1" }],
    summaryIntro: "Pinned request context is active.",
  });

  assert.match(markup, /id="traffic-selection-inspector"/);
  assert.match(markup, /id="traffic-selection-actions"/);
  assert.match(markup, /req-42/);
});

test("renderTrafficOverviewAside reports pinned request posture and next links", () => {
  const markup = renderTrafficOverviewAside({
    errorEvents: [
      { error_type: "rate_limit" },
      { error_type: "timeout" },
    ],
    filters: {
      apiKeyName: "",
      endpoint: "/v1/chat/completions",
      errorType: "",
      limit: "25",
      method: "POST",
      model: "",
      provider: "gigachat",
      requestId: "req-42",
      source: "",
      statusCode: "",
    },
    keyEntryCount: 3,
    providerEntryCount: 2,
    requestPinned: true,
  });

  assert.match(markup, /Pinned request/);
  assert.match(markup, /req-42/);
  assert.match(markup, /Open errors/);
  assert.match(markup, /Open usage/);
});

test("renderErrorPreviewRows links focused errors and logs for request-scoped rows", () => {
  const markup = renderErrorPreviewRows(
    [
      {
        created_at: 1_700_000_000,
        endpoint: "/v1/chat/completions",
        error_type: "timeout",
        method: "POST",
        provider: "gigachat",
        request_id: "req-99",
      },
    ],
    {
      apiKeyName: "",
      endpoint: "",
      errorType: "",
      limit: "25",
      method: "",
      model: "",
      provider: "",
      requestId: "",
      source: "",
      statusCode: "",
    },
  );

  assert.match(markup, /Focus error/);
  assert.match(markup, /request_id=req-99/);
  assert.match(markup, /Open logs/);
});

test("renderUsagePreviewRows summarizes request, error, key, and model counts", () => {
  const markup = renderUsagePreviewRows([
    {
      api_keys: { keyA: 1, keyB: 1 },
      error_count: 2,
      models: { giga: 1, pro: 1, max: 1 },
      provider: "gigachat",
      request_count: 7,
      total_tokens: 1234,
    },
  ]);

  assert.match(markup, /7 requests · 2 errors/);
  assert.match(markup, /2 keys · 3 models/);
  assert.match(markup, /gigachat/);
});
