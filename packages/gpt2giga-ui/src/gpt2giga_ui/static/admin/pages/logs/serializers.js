import { pill, renderTable, } from "../../templates.js";
import { asRecord, escapeHtml, formatDurationMs, formatNumber, formatTimestamp, setQueryParamIfPresent, } from "../../utils.js";
import { DEFAULT_LIMIT, DEFAULT_LINES, MAX_LOG_LINES, MAX_TAIL_CONTEXT_ROWS, } from "./state.js";
export function readLogsFilters() {
    const params = new URLSearchParams(window.location.search);
    return {
        lines: params.get("lines") || DEFAULT_LINES,
        query: params.get("query") || "",
        requestId: params.get("request_id") || "",
        provider: params.get("provider") || "",
        method: params.get("method") || "",
        statusCode: params.get("status_code") || "",
        errorType: params.get("error_type") || "",
        limit: params.get("limit") || DEFAULT_LIMIT,
    };
}
export function buildLogsEventQuery(filters) {
    const params = new URLSearchParams();
    params.set("limit", filters.limit || DEFAULT_LIMIT);
    setQueryParamIfPresent(params, "request_id", filters.requestId);
    setQueryParamIfPresent(params, "provider", filters.provider);
    setQueryParamIfPresent(params, "method", filters.method);
    setQueryParamIfPresent(params, "status_code", filters.statusCode);
    setQueryParamIfPresent(params, "error_type", filters.errorType);
    return params.toString();
}
export function buildLogsTailApiUrl(filters) {
    return `/admin/api/logs?lines=${encodeURIComponent(filters.lines || DEFAULT_LINES)}`;
}
export function buildLogsUrl(filters) {
    const params = new URLSearchParams();
    setQueryParamIfPresent(params, "lines", filters.lines, DEFAULT_LINES);
    setQueryParamIfPresent(params, "query", filters.query);
    setQueryParamIfPresent(params, "request_id", filters.requestId);
    setQueryParamIfPresent(params, "provider", filters.provider);
    setQueryParamIfPresent(params, "method", filters.method);
    setQueryParamIfPresent(params, "status_code", filters.statusCode);
    setQueryParamIfPresent(params, "error_type", filters.errorType);
    setQueryParamIfPresent(params, "limit", filters.limit, DEFAULT_LIMIT);
    const query = params.toString();
    return query ? `/admin/logs?${query}` : "/admin/logs";
}
export function buildTrafficUrlForRequest(requestId, filters) {
    const params = new URLSearchParams();
    const scopedRequestId = requestId.trim() || filters?.requestId?.trim() || "";
    setQueryParamIfPresent(params, "request_id", scopedRequestId);
    setQueryParamIfPresent(params, "provider", filters?.provider || "");
    setQueryParamIfPresent(params, "method", filters?.method || "");
    setQueryParamIfPresent(params, "status_code", filters?.statusCode || "");
    setQueryParamIfPresent(params, "error_type", filters?.errorType || "");
    setQueryParamIfPresent(params, "limit", filters?.limit || "", DEFAULT_LIMIT);
    const query = params.toString();
    return query ? `/admin/traffic?${query}` : "/admin/traffic";
}
export function normalizeLogText(text) {
    return text
        .split(/\r?\n/u)
        .map((line) => line.trimEnd())
        .filter((line) => line.length > 0)
        .slice(-MAX_LOG_LINES);
}
export function formatRenderedLogOutput(lines, filters) {
    const filtered = filterLogLines(lines, filters);
    return filtered.length ? filtered.join("\n") : "No log lines matched the current filters.";
}
export function filterLogLines(lines, filters) {
    const normalizedNeedles = [filters.query, filters.requestId]
        .map((value) => value.trim().toLowerCase())
        .filter(Boolean);
    if (!normalizedNeedles.length) {
        return lines;
    }
    return lines.filter((line) => {
        const normalizedLine = line.toLowerCase();
        return normalizedNeedles.every((needle) => normalizedLine.includes(needle));
    });
}
export function countMatchingLines(lines, filters) {
    return formatNumber(filterLogLines(lines, filters).length);
}
export function summarizeActiveFilters(filters) {
    const active = [
        filters.requestId ? `request=${filters.requestId}` : "",
        filters.provider ? `provider=${filters.provider}` : "",
        filters.method ? `method=${filters.method}` : "",
        filters.statusCode ? `status=${filters.statusCode}` : "",
        filters.errorType ? `error=${filters.errorType}` : "",
        filters.query ? `text=${filters.query}` : "",
    ].filter(Boolean);
    return active.join(" · ");
}
export function renderLogSelectionActions(requestId, filters) {
    const actions = [];
    if (requestId) {
        actions.push(`<a class="button button--secondary" href="${escapeHtml(buildTrafficUrlForRequest(requestId, filters))}">Open traffic for request</a>`);
        if (filters.requestId !== requestId) {
            actions.push(`<button class="button" data-log-action="scope-request" data-request-id="${escapeHtml(requestId)}" type="button">Pin this request</button>`);
        }
    }
    if (filters.requestId) {
        actions.push('<button class="button button--secondary" data-log-action="clear-request-scope" type="button">Clear request pin</button>');
    }
    return actions.length
        ? actions.join("")
        : '<span class="muted">Select a tail-derived request line or a recent request/error row to open matching traffic context.</span>';
}
export function buildTailContextRows(lines, filters, requestLookup, errorLookup) {
    const rows = [];
    lines.forEach((line, index) => {
        if (!matchesLineToFilters(line, filters)) {
            return;
        }
        const requestId = extractRequestIdFromLogLine(line);
        if (!requestId) {
            return;
        }
        rows.push({
            rowId: `${index + 1}:${requestId}`,
            lineNumber: index + 1,
            line,
            requestId,
            requestEvent: requestLookup.get(requestId) ?? null,
            errorEvent: errorLookup.get(requestId) ?? null,
        });
    });
    return rows.slice(-MAX_TAIL_CONTEXT_ROWS).reverse();
}
export function renderTailContextTable(rows, filters) {
    return renderTable([
        { label: "Tail line" },
        { label: "Request id" },
        { label: "Structured context" },
        { label: "Actions" },
    ], rows.map((row) => [
        `<strong>#${escapeHtml(formatNumber(row.lineNumber))}</strong><br /><span class="muted">${escapeHtml(truncateText(row.line, 140))}</span>`,
        `<strong>${escapeHtml(row.requestId)}</strong><br /><span class="muted">${escapeHtml(describeTailContext(row))}</span>`,
        renderTailStructuredContext(row),
        `
        <div class="toolbar">
          <button class="button button--secondary" data-log-tail-detail="${escapeHtml(row.rowId)}" type="button">Inspect</button>
          <a class="button" href="${escapeHtml(buildTrafficUrlForRequest(row.requestId, filters))}">Open traffic</a>
        </div>
      `,
    ]), "No request ids were extracted from the current rendered tail. Expand the tail window, adjust the text filter, or inspect a recent request/error row instead.");
}
export function buildTailSelectionSummary(row) {
    return [
        { label: "Selection", value: "Tail-derived request line" },
        {
            label: "Request id",
            value: row.requestId,
            note: "This id was extracted from the rendered tail and can be handed off directly into Traffic.",
        },
        {
            label: "Tail line",
            value: `#${formatNumber(row.lineNumber)}`,
            note: truncateText(row.line, 180),
        },
        {
            label: "Recent request",
            value: row.requestEvent ? "Loaded" : "Not in current window",
            note: row.requestEvent
                ? summarizeRouteStatus(row.requestEvent)
                : "The request event feed does not currently include this request id.",
        },
        {
            label: "Recent error",
            value: row.errorEvent ? "Loaded" : "Not in current window",
            note: row.errorEvent
                ? summarizeRouteStatus(row.errorEvent)
                : "No matching error event is loaded for this request id.",
        },
    ];
}
export function buildLogEventSelectionSummary(kind, item, counterpart) {
    const requestId = normalizeOptionalText(item.request_id);
    const tokenUsage = asRecord(item.token_usage);
    return [
        { label: "Selection", value: kind === "error" ? "Recent error event" : "Recent request event" },
        {
            label: "Request id",
            value: requestId || "n/a",
            note: requestId
                ? "Use this id to pin Logs or jump into the matching Traffic context with compatible filters still applied."
                : "This row cannot drive the cross-page request handoff because no request id was recorded.",
        },
        {
            label: "Route",
            value: `${String(item.method ?? "GET")} ${String(item.endpoint ?? item.path ?? "n/a")}`,
        },
        {
            label: "Provider",
            value: String(item.provider ?? "unknown"),
            note: String(item.model ?? item.api_key_name ?? item.api_key_source ?? "no model or key recorded"),
        },
        {
            label: "Status",
            value: formatNumber(item.status_code ?? 0),
            note: kind === "error" ? String(item.error_type ?? "request failed") : summarizeTokenUsage(tokenUsage),
        },
        {
            label: "Timing",
            value: formatDurationMs(item.stream_duration_ms ?? item.duration_ms),
            note: String(item.client_ip ?? "client hidden"),
        },
        {
            label: kind === "error" ? "Matching recent request" : "Matching recent error",
            value: counterpart ? "Loaded in the current window" : requestId ? "Not in the current window" : "Unavailable",
            note: counterpart ? summarizeRouteStatus(counterpart) : undefined,
        },
    ];
}
export function buildStreamDiagnostics(streamState, bufferLines) {
    return [
        {
            label: "Phase",
            value: streamState.phase,
            note: streamState.phase === "stopping" ? "Waiting for the active SSE reader to unwind." : streamState.note,
        },
        {
            label: "Session",
            value: streamState.sessionId ? `#${formatNumber(streamState.sessionId)}` : "No live session yet",
        },
        {
            label: "Buffer",
            value: `${formatNumber(bufferLines)} lines`,
            note: `${formatNumber(streamState.appendedLines)} appended during the last live session`,
        },
        {
            label: "Started",
            value: streamState.startedAt ? formatTimestamp(new Date(streamState.startedAt).toISOString()) : "n/a",
        },
        {
            label: "Last line",
            value: streamState.lastEventAt ? formatTimestamp(new Date(streamState.lastEventAt).toISOString()) : "n/a",
            note: streamState.lastError || undefined,
        },
    ];
}
export function describeStreamPhase(phase) {
    if (phase === "connecting") {
        return { label: "connecting", tone: "warn", buttonLabel: "Stop live stream" };
    }
    if (phase === "streaming") {
        return { label: "streaming", tone: "good", buttonLabel: "Stop live stream" };
    }
    if (phase === "stopping") {
        return { label: "stopping", tone: "warn", buttonLabel: "Stopping..." };
    }
    if (phase === "error") {
        return { label: "error", tone: "warn", buttonLabel: "Restart live stream" };
    }
    return { label: "idle", tone: "default", buttonLabel: "Start live stream" };
}
export function indexEventsByRequestId(events) {
    const index = new Map();
    events.forEach((event) => {
        const requestId = normalizeOptionalText(event.request_id);
        if (requestId && !index.has(requestId)) {
            index.set(requestId, event);
        }
    });
    return index;
}
export function seedLogsSelection(filters, requestLookup, errorLookup, rawLogLines, setSelectionFromEvent, setSelectionFromTailRow) {
    if (!filters.requestId) {
        return;
    }
    const requestEvent = requestLookup.get(filters.requestId);
    if (requestEvent) {
        setSelectionFromEvent("request", requestEvent);
        return;
    }
    const errorEvent = errorLookup.get(filters.requestId);
    if (errorEvent) {
        setSelectionFromEvent("error", errorEvent);
        return;
    }
    const tailRow = buildTailContextRows(rawLogLines, filters, requestLookup, errorLookup).find((row) => row.requestId === filters.requestId);
    if (tailRow) {
        setSelectionFromTailRow(tailRow);
    }
}
function describeTailContext(row) {
    if (row.requestEvent && row.errorEvent) {
        return "request + error context loaded";
    }
    if (row.errorEvent) {
        return "error context loaded";
    }
    if (row.requestEvent) {
        return "request context loaded";
    }
    return "tail line only";
}
function renderTailStructuredContext(row) {
    const source = row.errorEvent ?? row.requestEvent;
    if (!source) {
        return '<span class="muted">No structured request/error record for this request id in the current window.</span>';
    }
    const route = `${String(source.method ?? "GET")} ${String(source.endpoint ?? source.path ?? "n/a")}`;
    const note = row.errorEvent
        ? `${formatNumber(row.errorEvent.status_code ?? 0)} · ${String(row.errorEvent.error_type ?? "error event")}`
        : `${formatNumber(source.status_code ?? 0)} · ${String(source.model ?? "request event")}`;
    return `${escapeHtml(route)}<br /><span class="muted">${escapeHtml(note)}</span>`;
}
function extractRequestIdFromLogLine(line) {
    const pipeMatch = line.match(/^\s*[^|]+\|\s*[^|]+\|\s*([^|]+?)\s*\|/u);
    const pipeValue = pipeMatch?.[1]?.trim();
    if (pipeValue && pipeValue !== "-") {
        return pipeValue;
    }
    const explicitMatch = line.match(/\brequest_id[=:]\s*([A-Za-z0-9._:-]+)/iu);
    if (explicitMatch?.[1]) {
        return explicitMatch[1];
    }
    const bracketedMatch = line.match(/\[([A-Za-z0-9._:-]{6,})\]/u);
    return bracketedMatch?.[1] ?? "";
}
function matchesLineToFilters(line, filters) {
    return filterLogLines([line], filters).length > 0;
}
function renderEventRowActions(index, kind, requestId, filters) {
    const actions = [
        `<button class="button button--secondary" data-log-detail="${index}" data-log-kind="${kind}" type="button">Inspect</button>`,
    ];
    if (requestId.trim()) {
        actions.push(`<a class="button" href="${escapeHtml(buildTrafficUrlForRequest(requestId, filters))}">Open traffic</a>`);
    }
    return `<div class="toolbar">${actions.join("")}</div>`;
}
function summarizeRouteStatus(event) {
    return `${String(event.method ?? "GET")} ${String(event.endpoint ?? event.path ?? "n/a")} · status ${formatNumber(event.status_code ?? 0)}`;
}
function summarizeTokenUsage(usage) {
    if (Object.keys(usage).length === 0) {
        return "No token usage recorded";
    }
    return `${formatNumber(usage.total_tokens ?? 0)} total tokens`;
}
function normalizeOptionalText(value) {
    return String(value ?? "").trim();
}
function truncateText(value, maxLength) {
    if (value.length <= maxLength) {
        return value;
    }
    return `${value.slice(0, Math.max(0, maxLength - 3))}...`;
}
export function renderStreamPill(phase) {
    const { label, tone } = describeStreamPhase(phase);
    return pill(label, tone);
}
export function renderErrorRows(events, filters) {
    return renderTable([
        { label: "When" },
        { label: "Failure" },
        { label: "Route" },
        { label: "Actions" },
    ], events.map((event, index) => [
        `<strong>${escapeHtml(formatTimestamp(event.created_at))}</strong><br /><span class="muted">${escapeHtml(String(event.request_id ?? "no request id"))}</span>`,
        `<strong>${escapeHtml(String(event.error_type ?? "HTTP error"))}</strong><br /><span class="muted">status ${escapeHtml(formatNumber(event.status_code ?? 0))}</span>`,
        `${escapeHtml(String(event.provider ?? "unknown"))}<br /><span class="muted">${escapeHtml(`${String(event.method ?? "GET")} ${String(event.endpoint ?? event.path ?? "n/a")}`)}</span>`,
        renderEventRowActions(index, "error", String(event.request_id ?? ""), filters),
    ]), "No recent errors matched the current filters.");
}
export function renderRequestRows(events, filters) {
    return renderTable([
        { label: "When" },
        { label: "Latency" },
        { label: "Route" },
        { label: "Actions" },
    ], events.map((event, index) => [
        `<strong>${escapeHtml(formatTimestamp(event.created_at))}</strong><br /><span class="muted">${escapeHtml(String(event.request_id ?? "no request id"))}</span>`,
        `<strong>${escapeHtml(formatDurationMs(event.stream_duration_ms ?? event.duration_ms))}</strong><br /><span class="muted">status ${escapeHtml(formatNumber(event.status_code ?? 0))}</span>`,
        `${escapeHtml(String(event.provider ?? "unknown"))}<br /><span class="muted">${escapeHtml(`${String(event.method ?? "GET")} ${String(event.endpoint ?? event.path ?? "n/a")}`)}</span>`,
        renderEventRowActions(index, "request", String(event.request_id ?? ""), filters),
    ]), "No recent requests matched the current filters.");
}
