import { card, kpi, pill, renderDefinitionList, renderFilterSelectOptions, renderStaticSelectOptions, renderTable, } from "../templates.js";
import { asArray, asRecord, escapeHtml, formatDurationMs, formatNumber, formatTimestamp, setQueryParamIfPresent, toErrorMessage, } from "../utils.js";
const DEFAULT_LINES = "150";
const DEFAULT_LIMIT = "8";
const MAX_LOG_LINES = 4000;
const MAX_TAIL_CONTEXT_ROWS = 12;
export async function renderLogs(app, token) {
    const filters = readLogsFilters();
    const [tail, recentRequests, recentErrors] = await Promise.all([
        app.api.text(`/admin/api/logs?lines=${encodeURIComponent(filters.lines || DEFAULT_LINES)}`),
        app.api.json(`/admin/api/requests/recent?${buildLogsEventQuery(filters)}`),
        app.api.json(`/admin/api/errors/recent?${buildLogsEventQuery(filters)}`),
    ]);
    if (!app.isCurrentRender(token)) {
        return;
    }
    const requestEvents = asArray(recentRequests.events);
    const errorEvents = asArray(recentErrors.events);
    const requestLookup = indexEventsByRequestId(requestEvents);
    const errorLookup = indexEventsByRequestId(errorEvents);
    let rawLogLines = normalizeLogText(tail);
    let streamController = null;
    let autoScroll = true;
    let nextStreamSessionId = 0;
    const streamState = {
        phase: "idle",
        sessionId: 0,
        startedAt: null,
        lastEventAt: null,
        appendedLines: 0,
        note: "Tail buffer loaded from the file on disk.",
        lastError: "",
    };
    app.setHeroActions(`
    <button class="button button--secondary" id="reset-log-filters" type="button">Reset filters</button>
    <button class="button button--secondary" id="refresh-logs" type="button">Refresh tail</button>
    <button class="button" id="toggle-stream" type="button">Start live stream</button>
  `);
    app.setContent(`
    ${kpi("Tail lines", filters.lines || DEFAULT_LINES)}
    ${kpi("Matching lines", countMatchingLines(rawLogLines, filters))}
    ${kpi("Recent errors", formatNumber(errorEvents.length))}
    ${kpi("Recent requests", formatNumber(requestEvents.length))}
    ${card("Log filters", `
        <form id="logs-filters-form" class="stack">
          <div class="dual-grid">
            <label class="field">
              <span>Tail lines</span>
              <select name="lines">
                ${renderStaticSelectOptions(filters.lines || DEFAULT_LINES, ["100", "150", "250", "500", "1000"])}
              </select>
            </label>
            <label class="field">
              <span>Text match</span>
              <input name="query" value="${escapeHtml(filters.query)}" placeholder="Filter the rendered tail client-side" />
            </label>
          </div>
          <div class="dual-grid">
            <label class="field">
              <span>Request id</span>
              <input
                name="request_id"
                value="${escapeHtml(filters.requestId)}"
                placeholder="Pin one request across logs and traffic"
              />
            </label>
            <div class="surface">
              <div class="stack">
                <h4>Request scope</h4>
                <p class="muted">
                  Request pinning narrows the recent request/error context panels, tail-derived request
                  context, and the rendered tail by one request id so Traffic handoff stays one click away.
                </p>
              </div>
            </div>
          </div>
          <div class="quad-grid">
            <label class="field">
              <span>Provider</span>
              <select name="provider">
                ${renderFilterSelectOptions(filters.provider, [
        ...asArray(asRecord(recentRequests.available_filters).provider),
        ...asArray(asRecord(recentErrors.available_filters).provider),
    ])}
              </select>
            </label>
            <label class="field">
              <span>Method</span>
              <select name="method">
                ${renderFilterSelectOptions(filters.method, [
        ...asArray(asRecord(recentRequests.available_filters).method),
        ...asArray(asRecord(recentErrors.available_filters).method),
    ])}
              </select>
            </label>
            <label class="field">
              <span>Status code</span>
              <select name="status_code">
                ${renderFilterSelectOptions(filters.statusCode, [
        ...asArray(asRecord(recentRequests.available_filters).status_code),
        ...asArray(asRecord(recentErrors.available_filters).status_code),
    ])}
              </select>
            </label>
            <label class="field">
              <span>Error type</span>
              <select name="error_type">
                ${renderFilterSelectOptions(filters.errorType, asArray(asRecord(recentErrors.available_filters).error_type))}
              </select>
            </label>
          </div>
          <div class="toolbar">
            <label class="field">
              <span>Recent event limit</span>
              <select name="limit">
                ${renderStaticSelectOptions(filters.limit || DEFAULT_LIMIT, ["5", "8", "12", "20"])}
              </select>
            </label>
            <span class="muted">Filters scope the request/error context panels, tail-derived request links, and the tail viewer in one place.</span>
          </div>
          <div class="toolbar">
            <button class="button" type="submit">Apply filters</button>
            <a class="button button--secondary" href="${escapeHtml(filters.requestId ? buildTrafficUrlForRequest(filters.requestId) : "/admin/traffic")}">
              ${escapeHtml(filters.requestId ? "Open pinned traffic" : "Open traffic")}
            </a>
          </div>
        </form>
      `, "panel panel--span-12")}
    ${card("Stream controls", `
        <div class="surface">
          <div class="stack">
            <div class="surface__header">
              <div class="stack">
                <h4>Live tail status</h4>
                <p class="muted">SSE lifecycle is tracked explicitly so stop/reload flows do not leave a hanging stream reader behind.</p>
              </div>
              <div class="surface__meta" id="logs-stream-status">${pill("idle")}</div>
            </div>
            <div class="toolbar">
              <label class="checkbox-field">
                <input id="logs-auto-scroll" type="checkbox" checked />
                <span>Auto-scroll while streaming</span>
              </label>
              <button class="button button--secondary" id="clear-log-output" type="button">Clear buffer</button>
              <span class="muted" id="logs-stream-note">Tail buffer loaded from the file on disk.</span>
            </div>
            <div id="logs-stream-diagnostics">
              ${renderDefinitionList(buildStreamDiagnostics(streamState, rawLogLines.length))}
            </div>
          </div>
        </div>
      `, "panel panel--span-4")}
    ${card("Context inspector", `
        <div class="surface">
          <div class="stack">
            <div id="logs-selection-summary">
              ${renderDefinitionList([
        { label: "Selection", value: "No context selected" },
        { label: "Filters", value: summarizeActiveFilters(filters) || "No event filters" },
        {
            label: "Request scope",
            value: filters.requestId || "Recent log window",
            note: filters.requestId
                ? "The rendered tail, tail-derived request links, and event panels are pinned to one request id."
                : "Select a tail-derived request link or a recent request/error row to inspect context.",
        },
    ], "No event selected yet.")}
            </div>
            <div class="toolbar" id="logs-selection-actions">
              ${renderLogSelectionActions(null, filters)}
            </div>
            <pre class="code-block" id="logs-detail">${escapeHtml(JSON.stringify({
        filters,
        requests_loaded: requestEvents.length,
        errors_loaded: errorEvents.length,
    }, null, 2))}</pre>
          </div>
        </div>
      `, "panel panel--span-4")}
    ${card("Tail-derived request context", `
        <div id="logs-tail-context">
          ${renderTailContextTable(buildTailContextRows(rawLogLines, filters, requestLookup, errorLookup))}
        </div>
      `, "panel panel--span-4")}
    ${card("Rendered log tail", `
        <div class="surface surface--dark">
          <div class="stack">
            <div class="surface__header">
              <div class="stack">
                <h4>Rendered output</h4>
                <p class="muted">Client-side filtering is applied after fetching the selected tail window. Use the tail-derived context panel to jump from matching lines into structured request data.</p>
              </div>
              <div class="surface__meta">
                <span class="pill" id="logs-match-count">${escapeHtml(`${countMatchingLines(rawLogLines, filters)} matches`)}</span>
              </div>
            </div>
            <pre class="code-block code-block--tall" id="log-output">${escapeHtml(formatRenderedLogOutput(rawLogLines, filters))}</pre>
          </div>
        </div>
      `, "panel panel--span-12")}
    ${card("Recent errors", renderTable([
        { label: "When" },
        { label: "Failure" },
        { label: "Route" },
        { label: "Actions" },
    ], errorEvents.map((event, index) => [
        `<strong>${escapeHtml(formatTimestamp(event.created_at))}</strong><br /><span class="muted">${escapeHtml(String(event.request_id ?? "no request id"))}</span>`,
        `<strong>${escapeHtml(String(event.error_type ?? "HTTP error"))}</strong><br /><span class="muted">status ${escapeHtml(formatNumber(event.status_code ?? 0))}</span>`,
        `${escapeHtml(String(event.provider ?? "unknown"))}<br /><span class="muted">${escapeHtml(`${String(event.method ?? "GET")} ${String(event.endpoint ?? event.path ?? "n/a")}`)}</span>`,
        renderEventRowActions(index, "error", String(event.request_id ?? ""), buildTrafficUrlForRequest),
    ]), "No recent errors matched the current filters."), "panel panel--span-6")}
    ${card("Recent requests", renderTable([
        { label: "When" },
        { label: "Latency" },
        { label: "Route" },
        { label: "Actions" },
    ], requestEvents.map((event, index) => [
        `<strong>${escapeHtml(formatTimestamp(event.created_at))}</strong><br /><span class="muted">${escapeHtml(String(event.request_id ?? "no request id"))}</span>`,
        `<strong>${escapeHtml(formatDurationMs(event.stream_duration_ms ?? event.duration_ms))}</strong><br /><span class="muted">status ${escapeHtml(formatNumber(event.status_code ?? 0))}</span>`,
        `${escapeHtml(String(event.provider ?? "unknown"))}<br /><span class="muted">${escapeHtml(`${String(event.method ?? "GET")} ${String(event.endpoint ?? event.path ?? "n/a")}`)}</span>`,
        renderEventRowActions(index, "request", String(event.request_id ?? ""), buildTrafficUrlForRequest),
    ]), "No recent requests matched the current filters."), "panel panel--span-6")}
  `);
    const refreshButton = document.getElementById("refresh-logs");
    const resetFiltersButton = document.getElementById("reset-log-filters");
    const streamButton = document.getElementById("toggle-stream");
    const clearButton = app.pageContent.querySelector("#clear-log-output");
    const filtersForm = app.pageContent.querySelector("#logs-filters-form");
    const logOutput = app.pageContent.querySelector("#log-output");
    const matchCount = app.pageContent.querySelector("#logs-match-count");
    const streamStatus = app.pageContent.querySelector("#logs-stream-status");
    const streamNote = app.pageContent.querySelector("#logs-stream-note");
    const streamDiagnostics = app.pageContent.querySelector("#logs-stream-diagnostics");
    const autoScrollToggle = app.pageContent.querySelector("#logs-auto-scroll");
    const detailNode = app.pageContent.querySelector("#logs-detail");
    const summaryNode = app.pageContent.querySelector("#logs-selection-summary");
    const actionsNode = app.pageContent.querySelector("#logs-selection-actions");
    const tailContextNode = app.pageContent.querySelector("#logs-tail-context");
    if (!refreshButton ||
        !resetFiltersButton ||
        !streamButton ||
        !clearButton ||
        !filtersForm ||
        !logOutput ||
        !matchCount ||
        !streamStatus ||
        !streamNote ||
        !streamDiagnostics ||
        !autoScrollToggle ||
        !detailNode ||
        !summaryNode ||
        !actionsNode ||
        !tailContextNode) {
        return;
    }
    const inspectPayloads = {
        request: requestEvents,
        error: errorEvents,
    };
    const isStreamActive = () => streamState.phase === "connecting" ||
        streamState.phase === "streaming" ||
        streamState.phase === "stopping";
    const setSelectionFromEvent = (kind, item) => {
        const requestId = normalizeOptionalText(item.request_id);
        const counterpart = requestId && kind === "request"
            ? (errorLookup.get(requestId) ?? null)
            : requestId
                ? (requestLookup.get(requestId) ?? null)
                : null;
        summaryNode.innerHTML = renderDefinitionList(buildLogEventSelectionSummary(kind, item, counterpart), "No event selected yet.");
        actionsNode.innerHTML = renderLogSelectionActions(requestId || null, filters);
        detailNode.textContent = JSON.stringify({
            selected_event: item,
            counterpart_event: counterpart,
        }, null, 2);
    };
    const setSelectionFromTailRow = (row) => {
        summaryNode.innerHTML = renderDefinitionList(buildTailSelectionSummary(row), "No tail-derived request context selected yet.");
        actionsNode.innerHTML = renderLogSelectionActions(row.requestId || null, filters);
        detailNode.textContent = JSON.stringify({
            selected_tail_line: {
                line_number: row.lineNumber,
                line: row.line,
                request_id: row.requestId,
            },
            matched_request_event: row.requestEvent,
            matched_error_event: row.errorEvent,
        }, null, 2);
    };
    const renderTailContext = () => {
        tailContextNode.innerHTML = renderTailContextTable(buildTailContextRows(rawLogLines, filters, requestLookup, errorLookup));
    };
    const renderStreamDiagnosticsPanel = () => {
        streamDiagnostics.innerHTML = renderDefinitionList(buildStreamDiagnostics(streamState, rawLogLines.length));
    };
    const setStreamVisuals = () => {
        const { label, tone, buttonLabel } = describeStreamPhase(streamState.phase);
        streamStatus.innerHTML = pill(label, tone);
        streamNote.textContent = streamState.note;
        streamButton.textContent = buttonLabel;
        streamButton.toggleAttribute("disabled", streamState.phase === "stopping");
        renderStreamDiagnosticsPanel();
    };
    const setRenderedLogs = () => {
        const rendered = formatRenderedLogOutput(rawLogLines, filters);
        const matchingLines = countMatchingLines(rawLogLines, filters);
        logOutput.textContent = rendered;
        matchCount.textContent = `${matchingLines} matches`;
        renderTailContext();
        if (autoScroll) {
            logOutput.scrollTop = logOutput.scrollHeight;
        }
    };
    const stopStream = (reason) => {
        if (!streamController || streamState.phase === "stopping") {
            return;
        }
        streamState.phase = "stopping";
        streamState.note = reason;
        setStreamVisuals();
        streamController.abort();
    };
    app.registerCleanup(() => {
        stopStream("Stopping live stream during page cleanup.");
    });
    const refreshLogs = async () => {
        const nextTail = await app.api.text(`/admin/api/logs?lines=${encodeURIComponent(filters.lines || DEFAULT_LINES)}`);
        rawLogLines = normalizeLogText(nextTail);
        setRenderedLogs();
        if (!isStreamActive()) {
            streamState.phase = streamState.phase === "error" ? "error" : "idle";
            streamState.note = "Tail refreshed from the file on disk.";
            setStreamVisuals();
        }
    };
    const appendLogLine = (line) => {
        if (!line.trim()) {
            return;
        }
        rawLogLines = [...rawLogLines, line].slice(-MAX_LOG_LINES);
        streamState.appendedLines += 1;
        streamState.lastEventAt = Date.now();
        setRenderedLogs();
        renderStreamDiagnosticsPanel();
    };
    const startStream = async () => {
        if (isStreamActive()) {
            return;
        }
        const sessionId = ++nextStreamSessionId;
        const controller = new AbortController();
        streamController = controller;
        streamState.phase = "connecting";
        streamState.sessionId = sessionId;
        streamState.startedAt = Date.now();
        streamState.lastEventAt = null;
        streamState.appendedLines = 0;
        streamState.lastError = "";
        streamState.note = "Opening the live SSE stream for new log lines.";
        setStreamVisuals();
        try {
            const response = await app.api.raw("/admin/api/logs/stream", {
                signal: controller.signal,
            });
            if (!response.body) {
                throw new Error("Log stream body is unavailable.");
            }
            if (controller.signal.aborted || !app.isCurrentRender(token) || streamState.sessionId !== sessionId) {
                return;
            }
            streamState.phase = "streaming";
            streamState.note = "New log lines are appended as they arrive.";
            setStreamVisuals();
            await readSseStream(response.body, (event) => {
                if (controller.signal.aborted || !app.isCurrentRender(token) || streamState.sessionId !== sessionId) {
                    return;
                }
                if (event.type === "error") {
                    streamState.phase = "error";
                    streamState.lastError = event.data || "Log stream reported an error.";
                    streamState.note = "Server-side stream error reported. Inspect the error and restart the stream.";
                    setStreamVisuals();
                    app.pushAlert(streamState.lastError, "warn");
                    return;
                }
                if (event.type === "message" && event.data) {
                    appendLogLine(event.data);
                }
            }, controller.signal);
            if (!controller.signal.aborted && !streamState.lastError) {
                streamState.note = "Live stream ended cleanly. The current tail remains available.";
            }
        }
        catch (error) {
            if (error instanceof DOMException && error.name === "AbortError") {
                if (!streamState.note) {
                    streamState.note = "Live stream stopped.";
                }
            }
            else {
                streamState.phase = "error";
                streamState.lastError = toErrorMessage(error);
                streamState.note = "Live SSE stream failed before the tail reader could settle.";
                setStreamVisuals();
                app.pushAlert(streamState.lastError, "danger");
            }
        }
        finally {
            if (streamController === controller) {
                streamController = null;
            }
            if (streamState.sessionId === sessionId && streamState.phase !== "error") {
                streamState.phase = "idle";
            }
            if (app.isCurrentRender(token)) {
                setStreamVisuals();
            }
        }
    };
    refreshButton.addEventListener("click", () => {
        void refreshLogs();
    });
    resetFiltersButton.addEventListener("click", () => {
        window.history.replaceState({}, "", "/admin/logs");
        void app.render("logs");
    });
    streamButton.addEventListener("click", () => {
        if (isStreamActive()) {
            stopStream("Stopping the current SSE session and releasing the stream reader.");
            return;
        }
        void startStream();
    });
    clearButton.addEventListener("click", () => {
        rawLogLines = [];
        setRenderedLogs();
        streamState.note = isStreamActive()
            ? "Buffer cleared locally while the live stream stays connected."
            : "Tail buffer cleared locally.";
        setStreamVisuals();
    });
    autoScrollToggle.addEventListener("change", () => {
        autoScroll = autoScrollToggle.checked;
    });
    filtersForm.addEventListener("submit", (event) => {
        event.preventDefault();
        const form = event.currentTarget;
        const fields = form.elements;
        const nextFilters = {
            lines: fields.lines.value || DEFAULT_LINES,
            query: fields.query.value.trim(),
            requestId: fields.request_id.value.trim(),
            provider: fields.provider.value,
            method: fields.method.value,
            statusCode: fields.status_code.value,
            errorType: fields.error_type.value,
            limit: fields.limit.value || DEFAULT_LIMIT,
        };
        window.history.replaceState({}, "", buildLogsUrl(nextFilters));
        void app.render("logs");
    });
    actionsNode.addEventListener("click", (event) => {
        const target = event.target;
        if (!(target instanceof Element)) {
            return;
        }
        const button = target.closest("[data-log-action]");
        if (!button) {
            return;
        }
        const action = button.dataset.logAction;
        if (action === "scope-request") {
            const requestId = button.dataset.requestId?.trim();
            if (!requestId) {
                return;
            }
            window.history.replaceState({}, "", buildLogsUrl({ ...filters, requestId }));
            void app.render("logs");
            return;
        }
        if (action === "clear-request-scope") {
            window.history.replaceState({}, "", buildLogsUrl({ ...filters, requestId: "" }));
            void app.render("logs");
        }
    });
    tailContextNode.addEventListener("click", (event) => {
        const target = event.target;
        if (!(target instanceof Element)) {
            return;
        }
        const button = target.closest("[data-log-tail-detail]");
        if (!button) {
            return;
        }
        const rowId = button.dataset.logTailDetail;
        if (!rowId) {
            return;
        }
        const row = buildTailContextRows(rawLogLines, filters, requestLookup, errorLookup).find((candidate) => candidate.rowId === rowId);
        if (!row) {
            return;
        }
        setSelectionFromTailRow(row);
    });
    app.pageContent.querySelectorAll("[data-log-detail]").forEach((button) => {
        button.addEventListener("click", () => {
            const kind = button.dataset.logKind;
            const indexValue = button.dataset.logDetail;
            if ((kind !== "request" && kind !== "error") || indexValue === undefined) {
                return;
            }
            const item = inspectPayloads[kind][Number(indexValue)];
            if (!item) {
                return;
            }
            setSelectionFromEvent(kind, item);
        });
    });
    setRenderedLogs();
    setStreamVisuals();
    seedLogsSelection(filters, requestLookup, errorLookup, rawLogLines, setSelectionFromEvent, setSelectionFromTailRow);
}
function readLogsFilters() {
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
function buildLogsEventQuery(filters) {
    const params = new URLSearchParams();
    params.set("limit", filters.limit || DEFAULT_LIMIT);
    setQueryParamIfPresent(params, "request_id", filters.requestId);
    setQueryParamIfPresent(params, "provider", filters.provider);
    setQueryParamIfPresent(params, "method", filters.method);
    setQueryParamIfPresent(params, "status_code", filters.statusCode);
    setQueryParamIfPresent(params, "error_type", filters.errorType);
    return params.toString();
}
function buildLogsUrl(filters) {
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
function normalizeLogText(text) {
    return text
        .split(/\r?\n/u)
        .map((line) => line.trimEnd())
        .filter((line) => line.length > 0)
        .slice(-MAX_LOG_LINES);
}
function formatRenderedLogOutput(lines, filters) {
    const filtered = filterLogLines(lines, filters);
    return filtered.length ? filtered.join("\n") : "No log lines matched the current filters.";
}
function filterLogLines(lines, filters) {
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
function countMatchingLines(lines, filters) {
    return formatNumber(filterLogLines(lines, filters).length);
}
function summarizeActiveFilters(filters) {
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
function renderLogSelectionActions(requestId, filters) {
    const actions = [];
    if (requestId) {
        actions.push(`<a class="button button--secondary" href="${escapeHtml(buildTrafficUrlForRequest(requestId))}">Open traffic for request</a>`);
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
function buildTrafficUrlForRequest(requestId) {
    const params = new URLSearchParams();
    if (requestId.trim()) {
        params.set("request_id", requestId.trim());
    }
    const query = params.toString();
    return query ? `/admin/traffic?${query}` : "/admin/traffic";
}
function buildTailContextRows(lines, filters, requestLookup, errorLookup) {
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
function renderTailContextTable(rows) {
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
          <a class="button" href="${escapeHtml(buildTrafficUrlForRequest(row.requestId))}">Open traffic</a>
        </div>
      `,
    ]), "No request ids were extracted from the current rendered tail. Expand the tail window, adjust the text filter, or inspect a recent request/error row instead.");
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
function buildTailSelectionSummary(row) {
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
            note: row.requestEvent ? summarizeRouteStatus(row.requestEvent) : "The request event feed does not currently include this request id.",
        },
        {
            label: "Recent error",
            value: row.errorEvent ? "Loaded" : "Not in current window",
            note: row.errorEvent ? summarizeRouteStatus(row.errorEvent) : "No matching error event is loaded for this request id.",
        },
    ];
}
function buildLogEventSelectionSummary(kind, item, counterpart) {
    const requestId = normalizeOptionalText(item.request_id);
    const tokenUsage = asRecord(item.token_usage);
    return [
        { label: "Selection", value: kind === "error" ? "Recent error event" : "Recent request event" },
        {
            label: "Request id",
            value: requestId || "n/a",
            note: requestId
                ? "Use this id to pin Logs or jump into the matching Traffic context."
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
function buildStreamDiagnostics(streamState, bufferLines) {
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
function describeStreamPhase(phase) {
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
function renderEventRowActions(index, kind, requestId, buildContextUrl) {
    const actions = [
        `<button class="button button--secondary" data-log-detail="${index}" data-log-kind="${kind}" type="button">Inspect</button>`,
    ];
    if (requestId.trim()) {
        actions.push(`<a class="button" href="${escapeHtml(buildContextUrl(requestId))}">Open traffic</a>`);
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
function indexEventsByRequestId(events) {
    const index = new Map();
    events.forEach((event) => {
        const requestId = normalizeOptionalText(event.request_id);
        if (requestId && !index.has(requestId)) {
            index.set(requestId, event);
        }
    });
    return index;
}
function seedLogsSelection(filters, requestLookup, errorLookup, rawLogLines, setSelectionFromEvent, setSelectionFromTailRow) {
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
async function readSseStream(stream, onEvent, signal) {
    const reader = stream.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    const abortReader = () => {
        void reader.cancel().catch(() => {
            // Ignore cancellation races when the stream has already closed.
        });
    };
    signal?.addEventListener("abort", abortReader, { once: true });
    try {
        while (true) {
            if (signal?.aborted) {
                throw new DOMException("The operation was aborted.", "AbortError");
            }
            const { value, done } = await reader.read();
            if (done) {
                buffer += decoder.decode();
                flushSseBuffer(buffer, onEvent);
                return;
            }
            buffer += decoder.decode(value, { stream: true });
            const frames = buffer.split(/\r?\n\r?\n/u);
            buffer = frames.pop() ?? "";
            frames.forEach((frame) => flushSseBuffer(frame, onEvent));
        }
    }
    finally {
        signal?.removeEventListener("abort", abortReader);
        reader.releaseLock();
    }
}
function flushSseBuffer(rawFrame, onEvent) {
    const frame = rawFrame.trim();
    if (!frame) {
        return;
    }
    let eventType = "message";
    const dataLines = [];
    frame.split(/\r?\n/u).forEach((line) => {
        if (!line || line.startsWith(":")) {
            return;
        }
        if (line.startsWith("event:")) {
            eventType = line.slice("event:".length).trim() || "message";
            return;
        }
        if (line.startsWith("data:")) {
            dataLines.push(line.slice("data:".length).trimStart());
        }
    });
    if (dataLines.length === 0 && eventType === "message") {
        return;
    }
    onEvent({ type: eventType, data: dataLines.join("\n") });
}
