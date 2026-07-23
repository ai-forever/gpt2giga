import type {
  TraceReplayAxis,
  TraceReplayProjection,
} from "./api";

export interface TraceReplayComparisonRow {
  key: "semantic" | "tools" | "diff" | "latency" | "cost";
  source: string;
  target: string;
  delta: string;
}

export function traceReplayTargetPlaceholder(axis: TraceReplayAxis): string {
  switch (axis) {
    case "provider":
      return "provider-id@revision";
    case "extensions":
      return "none or mcp_<id>@<sha256>";
    case "harness":
      return "harness-id";
    default:
      return "model-id";
  }
}

export function traceReplayComparisonRows(
  projection: TraceReplayProjection,
): TraceReplayComparisonRow[] {
  const comparison = projection.comparison;
  return [
    {
      key: "semantic",
      source: digest(comparison.semantic.source.sha256),
      target: digest(comparison.semantic.target?.sha256),
      delta: changed(comparison.semantic.changed),
    },
    {
      key: "tools",
      source: count(comparison.tools.source.event_count),
      target: count(comparison.tools.target?.event_count),
      delta: changed(comparison.tools.changed),
    },
    {
      key: "diff",
      source: digest(comparison.diff.source.sha256),
      target: digest(comparison.diff.target?.sha256),
      delta: changed(comparison.diff.changed),
    },
    {
      key: "latency",
      source: milliseconds(comparison.latency.source),
      target: milliseconds(comparison.latency.target),
      delta: signed(comparison.latency.delta, "ms"),
    },
    {
      key: "cost",
      source: cost(comparison.cost.source),
      target: cost(comparison.cost.target),
      delta: signed(comparison.cost.delta, ""),
    },
  ];
}

function digest(value: unknown): string {
  return typeof value === "string" && value.length >= 12 ? value.slice(0, 12) : "unknown";
}

function count(value: unknown): string {
  return typeof value === "number" ? value.toLocaleString() : "unknown";
}

function changed(value: boolean | null): string {
  if (value === null) return "pending";
  return value ? "changed" : "same";
}

function milliseconds(value: number | null): string {
  return value === null ? "unknown" : `${value.toLocaleString()} ms`;
}

function signed(value: number | null, unit: string): string {
  if (value === null) return "unknown";
  const suffix = unit ? ` ${unit}` : "";
  return `${value > 0 ? "+" : ""}${value.toLocaleString()}${suffix}`;
}

function cost(
  value: { value: number | null; unit: string | null; confidence: string } | null,
): string {
  if (value === null || value.value === null) return "unknown";
  return `${value.value.toLocaleString()} ${value.unit ?? ""} · ${value.confidence}`.trim();
}
