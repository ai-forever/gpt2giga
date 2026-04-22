import { INVALID_JSON } from "./forms-types.js";
import { safeJsonParse } from "./utils.js";

export function trimToNull(value: string): string | null {
  const normalized = value.trim();
  return normalized || null;
}

export function parseOptionalNumber(value: string): number | null {
  const normalized = value.trim();
  if (!normalized) {
    return null;
  }
  const numeric = Number(normalized);
  return Number.isFinite(numeric) ? numeric : null;
}

export function parseOptionalJsonObject(
  value: string,
): Record<string, string> | typeof INVALID_JSON | null {
  const normalized = value.trim();
  if (!normalized) {
    return null;
  }
  const parsed = safeJsonParse<unknown>(normalized, INVALID_JSON);
  if (!parsed || parsed === INVALID_JSON || typeof parsed !== "object" || Array.isArray(parsed)) {
    return INVALID_JSON;
  }
  return Object.entries(parsed as Record<string, unknown>).reduce<Record<string, string>>(
    (result, [key, item]) => {
      result[key] = String(item);
      return result;
    },
    {},
  );
}

export function asComparableRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}
