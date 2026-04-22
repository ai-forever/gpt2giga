import { INVALID_JSON } from "./forms-types.js";
import { safeJsonParse } from "./utils.js";
export function trimToNull(value) {
    const normalized = value.trim();
    return normalized || null;
}
export function parseOptionalNumber(value) {
    const normalized = value.trim();
    if (!normalized) {
        return null;
    }
    const numeric = Number(normalized);
    return Number.isFinite(numeric) ? numeric : null;
}
export function parseOptionalJsonObject(value) {
    const normalized = value.trim();
    if (!normalized) {
        return null;
    }
    const parsed = safeJsonParse(normalized, INVALID_JSON);
    if (!parsed || parsed === INVALID_JSON || typeof parsed !== "object" || Array.isArray(parsed)) {
        return INVALID_JSON;
    }
    return Object.entries(parsed).reduce((result, [key, item]) => {
        result[key] = String(item);
        return result;
    }, {});
}
export function asComparableRecord(value) {
    return value && typeof value === "object" && !Array.isArray(value)
        ? value
        : {};
}
