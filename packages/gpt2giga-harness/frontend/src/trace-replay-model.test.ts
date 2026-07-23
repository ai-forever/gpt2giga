import { describe, expect, it } from "vitest";

import type { TraceReplayProjection } from "./api";
import {
  traceReplayComparisonRows,
  traceReplayTargetPlaceholder,
} from "./trace-replay-model";

describe("Trace replay model", () => {
  it("keeps every axis target explicit", () => {
    expect(traceReplayTargetPlaceholder("model")).toBe("model-id");
    expect(traceReplayTargetPlaceholder("provider")).toBe("provider-id@revision");
    expect(traceReplayTargetPlaceholder("harness")).toBe("harness-id");
    expect(traceReplayTargetPlaceholder("extensions")).toContain("mcp_<id>@<sha256>");
  });

  it("renders bounded comparisons without converting unknown cost to zero", () => {
    const projection = {
      comparison: {
        semantic: {
          source: { sha256: "a".repeat(64) },
          target: { sha256: "b".repeat(64) },
          changed: true,
        },
        tools: {
          source: { event_count: 1 },
          target: { event_count: 3 },
          changed: true,
        },
        diff: {
          source: { sha256: null },
          target: { sha256: null },
          changed: false,
        },
        latency: { source: 100, target: 125, delta: 25, unit: "milliseconds" },
        cost: {
          source: { value: null, unit: null, confidence: "unknown" },
          target: { value: null, unit: null, confidence: "unknown" },
          delta: null,
        },
      },
    } as unknown as TraceReplayProjection;

    expect(traceReplayComparisonRows(projection)).toEqual([
      { key: "semantic", source: "aaaaaaaaaaaa", target: "bbbbbbbbbbbb", delta: "changed" },
      { key: "tools", source: "1", target: "3", delta: "changed" },
      { key: "diff", source: "unknown", target: "unknown", delta: "same" },
      { key: "latency", source: "100 ms", target: "125 ms", delta: "+25 ms" },
      { key: "cost", source: "unknown", target: "unknown", delta: "unknown" },
    ]);
  });
});
