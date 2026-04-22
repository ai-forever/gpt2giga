import assert from "node:assert/strict";
import test from "node:test";

import {
  buildObservabilityDiffEntries,
  buildPendingDiffEntries,
  describePendingRuntimeImpact,
  summarizePendingChanges,
} from "../../gpt2giga/frontend/admin/forms.js";

test("buildPendingDiffEntries renders Gigachat secret changes with configured previews", () => {
  const entries = buildPendingDiffEntries(
    "gigachat",
    {
      timeout: 30,
      access_token_configured: true,
      access_token_preview: "configured (masked)",
    },
    {
      timeout: 30,
      access_token: "new-token",
    },
  );

  assert.deepEqual(entries, [
    {
      field: "access_token",
      current: "configured (masked)",
      target: "updated secret",
    },
  ]);
});

test("buildObservabilityDiffEntries exposes replaceable secrets and header updates", () => {
  const entries = buildObservabilityDiffEntries(
    {
      enable_telemetry: false,
      active_sinks: [],
      otlp: {
        headers_configured: true,
        header_names: ["authorization"],
      },
      langfuse: {
        public_key_configured: false,
        secret_key_configured: true,
        secret_key_preview: "masked",
      },
      phoenix: {},
    },
    {
      enable_telemetry: true,
      active_sinks: ["otlp", "langfuse"],
      otlp: {
        headers: { authorization: "Bearer demo" },
      },
      langfuse: {
        public_key: "pk-demo",
        secret_key: null,
      },
      phoenix: {},
    },
  );

  assert.deepEqual(entries, [
    { field: "enable_telemetry", current: false, target: true },
    { field: "active_sinks", current: [], target: ["otlp", "langfuse"] },
    {
      field: "otlp_headers",
      current: "configured (authorization)",
      target: "updated headers (authorization)",
    },
    {
      field: "langfuse_public_key",
      current: "not configured",
      target: "updated secret",
    },
    {
      field: "langfuse_secret_key",
      current: "masked",
      target: "clear value",
    },
  ]);
});

test("summarizePendingChanges and runtime impact distinguish restart-sensitive saves", () => {
  const summary = summarizePendingChanges([
    { field: "mode", current: "DEV", target: "PROD" },
    { field: "enable_telemetry", current: false, target: true },
    { field: "langfuse_secret_key", current: "masked", target: "updated secret" },
  ]);

  assert.deepEqual(summary, {
    changedFields: ["mode", "enable_telemetry", "langfuse_secret_key"],
    restartFields: ["mode"],
    liveFields: ["enable_telemetry", "langfuse_secret_key"],
    secretFields: ["langfuse_secret_key"],
  });
  assert.deepEqual(describePendingRuntimeImpact({ effectiveSummary: summary, blockedLiveFields: [] }), {
    label: "Runtime keeps current config until restart",
    tone: "warn",
    detail:
      "This save batch includes restart-sensitive fields, so the persisted target updates now but the running process keeps the previous runtime config until restart.",
  });
});

test("describePendingRuntimeImpact reports no-op form state", () => {
  assert.deepEqual(
    describePendingRuntimeImpact({
      effectiveSummary: {
        changedFields: [],
        restartFields: [],
        liveFields: [],
        secretFields: [],
      },
      blockedLiveFields: [],
    }),
    {
      label: "Runtime matches persisted target",
      tone: "good",
      detail: "The current form matches the saved control-plane state.",
    },
  );
});
