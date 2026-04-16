export const DEFAULT_LINES = "150";
export const DEFAULT_LIMIT = "8";
export const MAX_LOG_LINES = 4000;
export const MAX_TAIL_CONTEXT_ROWS = 12;
export function createLogsStreamState() {
    return {
        phase: "idle",
        sessionId: 0,
        startedAt: null,
        lastEventAt: null,
        appendedLines: 0,
        note: "Tail buffer loaded from the file on disk.",
        lastError: "",
    };
}
