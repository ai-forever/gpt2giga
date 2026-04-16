export interface LogsFilters {
  lines: string;
  query: string;
  requestId: string;
  provider: string;
  method: string;
  statusCode: string;
  errorType: string;
  limit: string;
}

export interface DefinitionItem {
  label: string;
  value: string;
  note?: string;
}

export type LogEvent = Record<string, unknown>;
export type LogSelectionKind = "request" | "error";
export type StreamPhase = "idle" | "connecting" | "streaming" | "stopping" | "error";

export interface LogsStreamEvent {
  type: string;
  data: string;
}

export interface LogsStreamState {
  phase: StreamPhase;
  sessionId: number;
  startedAt: number | null;
  lastEventAt: number | null;
  appendedLines: number;
  note: string;
  lastError: string;
}

export interface TailContextRow {
  rowId: string;
  lineNumber: number;
  line: string;
  requestId: string;
  requestEvent: LogEvent | null;
  errorEvent: LogEvent | null;
}

export const DEFAULT_LINES = "150";
export const DEFAULT_LIMIT = "8";
export const MAX_LOG_LINES = 4000;
export const MAX_TAIL_CONTEXT_ROWS = 12;

export function createLogsStreamState(): LogsStreamState {
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
