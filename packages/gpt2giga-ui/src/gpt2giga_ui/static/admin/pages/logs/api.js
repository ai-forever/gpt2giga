import { asArray } from "../../utils.js";
import { buildLogsEventQuery, buildLogsTailApiUrl, } from "./serializers.js";
export async function loadLogsPageData(app, filters) {
    const [tailText, recentRequestsPayload, recentErrorsPayload] = await Promise.all([
        app.api.text(buildLogsTailApiUrl(filters)),
        app.api.json(`/admin/api/requests/recent?${buildLogsEventQuery(filters)}`),
        app.api.json(`/admin/api/errors/recent?${buildLogsEventQuery(filters)}`),
    ]);
    return {
        tailText,
        recentRequestsPayload,
        recentErrorsPayload,
        requestEvents: asArray(recentRequestsPayload.events),
        errorEvents: asArray(recentErrorsPayload.events),
    };
}
export function loadLogTail(app, filters) {
    return app.api.text(buildLogsTailApiUrl(filters));
}
export function openLogsStream(app, signal) {
    return app.api.raw("/admin/api/logs/stream", { signal });
}
export async function readLogsSseStream(stream, onEvent, signal) {
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
