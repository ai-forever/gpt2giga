import assert from "node:assert/strict";
import test from "node:test";

import {
  buildLogsUrlForRequest,
  buildTrafficScopeSummary,
  buildTrafficUrl,
  summarizeTrafficFilters,
} from "../../gpt2giga/frontend/admin/pages/traffic/serializers.js";
import type { TrafficFilters } from "../../gpt2giga/frontend/admin/pages/traffic/state.js";

function readSearchParams(url: string): URLSearchParams {
  return new URL(url, "http://localhost").searchParams;
}

const BASE_FILTERS: TrafficFilters = {
  limit: "25",
  requestId: "",
  provider: "",
  endpoint: "",
  method: "",
  statusCode: "",
  model: "",
  errorType: "",
  source: "",
  apiKeyName: "",
};

test("buildTrafficUrl keeps non-default filters and page path", () => {
  const url = buildTrafficUrl(
    {
      ...BASE_FILTERS,
      provider: "gigachat",
      model: "giga-pro",
      limit: "100",
    },
    "traffic-usage",
  );

  assert.equal(new URL(url, "http://localhost").pathname, "/admin/traffic-usage");
  const params = readSearchParams(url);
  assert.equal(params.get("provider"), "gigachat");
  assert.equal(params.get("model"), "giga-pro");
  assert.equal(params.get("limit"), "100");
});

test("buildLogsUrlForRequest reuses scoped filters and omits default limit", () => {
  const url = buildLogsUrlForRequest("  ", {
    limit: "25",
    requestId: "req-42",
    provider: "gigachat",
    method: "POST",
    statusCode: "500",
    errorType: "upstream_error",
  });

  assert.equal(new URL(url, "http://localhost").pathname, "/admin/logs");
  const params = readSearchParams(url);
  assert.equal(params.get("request_id"), "req-42");
  assert.equal(params.get("provider"), "gigachat");
  assert.equal(params.get("method"), "POST");
  assert.equal(params.get("status_code"), "500");
  assert.equal(params.get("error_type"), "upstream_error");
  assert.equal(params.has("limit"), false);
});

test("buildTrafficScopeSummary uses request-scoped events when a request is pinned", () => {
  const summary = buildTrafficScopeSummary(
    { ...BASE_FILTERS, requestId: "req-7" },
    [
      { provider: "gigachat", token_usage: { total_tokens: 12 } },
      { provider: "gigachat", token_usage: { total_tokens: 30 } },
    ],
    [{ provider: "openai" }],
    [{ provider: "ignored" }],
    {
      request_count: 999,
      error_count: 999,
      total_tokens: 999,
    },
  );

  assert.deepEqual(summary, {
    requestCount: 2,
    errorCount: 1,
    totalTokens: 42,
    providerCount: 2,
  });
});

test("summarizeTrafficFilters renders active filters in operator-facing order", () => {
  const summary = summarizeTrafficFilters({
    ...BASE_FILTERS,
    requestId: "req-7",
    provider: "gigachat",
    method: "POST",
    statusCode: "429",
    source: "scoped",
  });

  assert.equal(
    summary,
    "request=req-7 · provider=gigachat · method=POST · status=429 · source=scoped",
  );
});
