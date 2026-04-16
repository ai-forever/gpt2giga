import { renderDefinitionList } from "../../templates.js";
import { toErrorMessage } from "../../utils.js";
import { loadLogTail, openLogsStream, readLogsSseStream, } from "./api.js";
import { buildLogEventSelectionSummary, buildLogsUrl, buildStreamDiagnostics, buildTailContextRows, buildTailSelectionSummary, countMatchingLines, describeStreamPhase, formatRenderedLogOutput, indexEventsByRequestId, normalizeLogText, renderLogSelectionActions, renderStreamPill, renderTailContextTable, seedLogsSelection, } from "./serializers.js";
import { createLogsStreamState, MAX_LOG_LINES, } from "./state.js";
export function bindLogsPage(options) {
    const { app, data, elements, filters, token } = options;
    const requestLookup = indexEventsByRequestId(data.requestEvents);
    const errorLookup = indexEventsByRequestId(data.errorEvents);
    const inspectPayloads = {
        request: data.requestEvents,
        error: data.errorEvents,
    };
    let rawLogLines = normalizeLogText(data.tailText);
    let streamController = null;
    let autoScroll = true;
    let nextStreamSessionId = 0;
    const streamState = createLogsStreamState();
    const isStreamActive = () => streamState.phase === "connecting" ||
        streamState.phase === "streaming" ||
        streamState.phase === "stopping";
    const setSelectionFromEvent = (kind, item) => {
        const requestId = String(item.request_id ?? "").trim();
        const counterpart = requestId && kind === "request"
            ? (errorLookup.get(requestId) ?? null)
            : requestId
                ? (requestLookup.get(requestId) ?? null)
                : null;
        elements.summaryNode.innerHTML = renderDefinitionList(buildLogEventSelectionSummary(kind, item, counterpart), "No event selected yet.");
        elements.actionsNode.innerHTML = renderLogSelectionActions(requestId || null, filters);
        elements.detailNode.textContent = JSON.stringify({
            selected_event: item,
            counterpart_event: counterpart,
        }, null, 2);
    };
    const setSelectionFromTailRow = (row) => {
        elements.summaryNode.innerHTML = renderDefinitionList(buildTailSelectionSummary(row), "No tail-derived request context selected yet.");
        elements.actionsNode.innerHTML = renderLogSelectionActions(row.requestId || null, filters);
        elements.detailNode.textContent = JSON.stringify({
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
        elements.tailContextNode.innerHTML = renderTailContextTable(buildTailContextRows(rawLogLines, filters, requestLookup, errorLookup));
    };
    const renderStreamDiagnosticsPanel = () => {
        elements.streamDiagnostics.innerHTML = renderDefinitionList(buildStreamDiagnostics(streamState, rawLogLines.length));
    };
    const setStreamVisuals = () => {
        const { buttonLabel } = describeStreamPhase(streamState.phase);
        elements.streamStatus.innerHTML = renderStreamPill(streamState.phase);
        elements.streamNote.textContent = streamState.note;
        elements.streamButton.textContent = buttonLabel;
        elements.streamButton.toggleAttribute("disabled", streamState.phase === "stopping");
        renderStreamDiagnosticsPanel();
    };
    const setRenderedLogs = () => {
        elements.logOutput.textContent = formatRenderedLogOutput(rawLogLines, filters);
        elements.matchCount.textContent = `${countMatchingLines(rawLogLines, filters)} matches`;
        renderTailContext();
        if (autoScroll) {
            elements.logOutput.scrollTop = elements.logOutput.scrollHeight;
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
    const refreshLogs = async () => {
        const nextTail = await loadLogTail(app, filters);
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
            const response = await openLogsStream(app, controller.signal);
            if (!response.body) {
                throw new Error("Log stream body is unavailable.");
            }
            if (controller.signal.aborted || !app.isCurrentRender(token) || streamState.sessionId !== sessionId) {
                return;
            }
            streamState.phase = "streaming";
            streamState.note = "New log lines are appended as they arrive.";
            setStreamVisuals();
            await readLogsSseStream(response.body, (event) => {
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
    elements.refreshButton.addEventListener("click", () => {
        void refreshLogs();
    });
    elements.resetFiltersButton.addEventListener("click", () => {
        window.history.replaceState({}, "", "/admin/logs");
        void app.render("logs");
    });
    elements.streamButton.addEventListener("click", () => {
        if (isStreamActive()) {
            stopStream("Stopping the current SSE session and releasing the stream reader.");
            return;
        }
        void startStream();
    });
    elements.clearButton.addEventListener("click", () => {
        rawLogLines = [];
        setRenderedLogs();
        streamState.note = isStreamActive()
            ? "Buffer cleared locally while the live stream stays connected."
            : "Tail buffer cleared locally.";
        setStreamVisuals();
    });
    elements.autoScrollToggle.addEventListener("change", () => {
        autoScroll = elements.autoScrollToggle.checked;
    });
    elements.filtersForm.addEventListener("submit", (event) => {
        event.preventDefault();
        const form = event.currentTarget;
        const fields = form.elements;
        const nextFilters = {
            lines: fields.lines.value,
            query: fields.query.value.trim(),
            requestId: fields.request_id.value.trim(),
            provider: fields.provider.value,
            method: fields.method.value,
            statusCode: fields.status_code.value,
            errorType: fields.error_type.value,
            limit: fields.limit.value,
        };
        window.history.replaceState({}, "", buildLogsUrl(nextFilters));
        void app.render("logs");
    });
    elements.actionsNode.addEventListener("click", (event) => {
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
    elements.tailContextNode.addEventListener("click", (event) => {
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
    app.registerCleanup(() => {
        stopStream("Stopping live stream during page cleanup.");
    });
    setRenderedLogs();
    setStreamVisuals();
    seedLogsSelection(filters, requestLookup, errorLookup, rawLogLines, setSelectionFromEvent, setSelectionFromTailRow);
}
