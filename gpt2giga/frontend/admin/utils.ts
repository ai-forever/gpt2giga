export function escapeHtml(value: unknown): string {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

export function csv(value: unknown): string {
  return Array.isArray(value) ? value.join(", ") : "";
}

export function parseCsv(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

export function uniqueSortedStrings(values: unknown[]): string[] {
  return Array.from(
    new Set(
      values
        .map((value) => String(value ?? "").trim())
        .filter(Boolean),
    ),
  ).sort((left, right) => left.localeCompare(right));
}

export function setQueryParamIfPresent(
  params: URLSearchParams,
  key: string,
  value: string,
  skipValue = "",
): void {
  if (value && value !== skipValue) {
    params.set(key, value);
  }
}

export function safeJsonParse<T>(value: string, fallback: T): T {
  try {
    return JSON.parse(value) as T;
  } catch {
    return fallback;
  }
}

export function humanizeField(field: string): string {
  return field
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

export function normalizeComparableValue(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map((item) => normalizeComparableValue(item));
  }

  if (value && typeof value === "object") {
    return Object.keys(value as Record<string, unknown>)
      .sort()
      .reduce<Record<string, unknown>>((result, key) => {
        result[key] = normalizeComparableValue(
          (value as Record<string, unknown>)[key],
        );
        return result;
      }, {});
  }

  return value ?? null;
}

export function formatTimestamp(value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return "n/a";
  }

  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    const parsed = new Date(String(value));
    return Number.isNaN(parsed.getTime())
      ? String(value)
      : parsed.toLocaleString();
  }

  return new Date(numeric * 1000).toLocaleString();
}

export function formatBytes(value: unknown): string {
  const numeric = Number(value ?? 0);
  if (!Number.isFinite(numeric) || numeric <= 0) {
    return "0 B";
  }

  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = numeric;
  let unitIndex = 0;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }
  const precision = size >= 100 || unitIndex === 0 ? 0 : 1;
  return `${size.toFixed(precision)} ${units[unitIndex]}`;
}

export function formatNumber(value: unknown): string {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return value === null || value === undefined || value === "" ? "0" : String(value);
  }
  return new Intl.NumberFormat().format(numeric);
}

export function formatDurationMs(value: unknown): string {
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || numeric <= 0) {
    return "0 ms";
  }
  if (numeric >= 1000) {
    return `${(numeric / 1000).toFixed(numeric >= 10_000 ? 0 : 1)} s`;
  }
  return `${Math.round(numeric)} ms`;
}

export function asArray<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

export function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

export function toErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
