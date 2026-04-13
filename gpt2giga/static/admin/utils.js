export function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;");
}
export function csv(value) {
    return Array.isArray(value) ? value.join(", ") : "";
}
export function parseCsv(value) {
    return value
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean);
}
export function safeJsonParse(value, fallback) {
    try {
        return JSON.parse(value);
    }
    catch {
        return fallback;
    }
}
export function humanizeField(field) {
    return field
        .split("_")
        .filter(Boolean)
        .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
        .join(" ");
}
export function normalizeComparableValue(value) {
    if (Array.isArray(value)) {
        return value.map((item) => normalizeComparableValue(item));
    }
    if (value && typeof value === "object") {
        return Object.keys(value)
            .sort()
            .reduce((result, key) => {
            result[key] = normalizeComparableValue(value[key]);
            return result;
        }, {});
    }
    return value ?? null;
}
export function formatTimestamp(value) {
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
export function formatBytes(value) {
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
export function asArray(value) {
    return Array.isArray(value) ? value : [];
}
export function asRecord(value) {
    return value && typeof value === "object" && !Array.isArray(value)
        ? value
        : {};
}
export function toErrorMessage(error) {
    return error instanceof Error ? error.message : String(error);
}
