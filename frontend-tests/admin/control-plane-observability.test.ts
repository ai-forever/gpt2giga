import assert from "node:assert/strict";
import test from "node:test";

import {
  buildSetupObservabilityHandoffState,
  describeOtlpHeaderPreview,
} from "../../gpt2giga/frontend/admin/pages/control-plane-sections.js";

test("describeOtlpHeaderPreview prefers named headers and falls back to configured flag", () => {
  assert.equal(
    describeOtlpHeaderPreview({
      header_names: ["authorization", "x-tenant"],
      headers_configured: true,
    }),
    "configured (authorization, x-tenant)",
  );
  assert.equal(
    describeOtlpHeaderPreview({
      headers_configured: true,
    }),
    "configured",
  );
  assert.equal(describeOtlpHeaderPreview({}), "not configured");
});

test("buildSetupObservabilityHandoffState summarizes enabled sinks and missing fields", () => {
  assert.deepEqual(
    buildSetupObservabilityHandoffState({
      enable_telemetry: true,
      active_sinks: ["otlp"],
      metrics_enabled: false,
      sinks: [
        {
          id: "otlp",
          label: "OTLP",
          enabled: true,
          configured: false,
          missing_fields: ["headers", "endpoint"],
        },
        {
          id: "phoenix",
          label: "Phoenix",
          enabled: true,
          configured: true,
          missing_fields: [],
        },
      ],
    }),
    {
      telemetryEnabled: true,
      activeSinkCount: 1,
      metricsEnabled: false,
      summaries: [
        {
          message: "OTLP is enabled but still missing: headers, endpoint.",
          tone: "warn",
        },
        {
          message: "Phoenix is enabled and ready for live exports.",
          tone: "info",
        },
      ],
    },
  );
});

test("buildSetupObservabilityHandoffState reports optional bootstrap posture when no sink is enabled", () => {
  assert.deepEqual(
    buildSetupObservabilityHandoffState({
      enable_telemetry: false,
      active_sinks: [],
      metrics_enabled: true,
      sinks: [],
    }),
    {
      telemetryEnabled: false,
      activeSinkCount: 0,
      metricsEnabled: true,
      summaries: [
        {
          message: "Observability is optional during bootstrap.",
          tone: "info",
        },
      ],
    },
  );
});
