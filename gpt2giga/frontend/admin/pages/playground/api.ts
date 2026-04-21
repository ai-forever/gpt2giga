import { toErrorMessage } from "../../utils.js";
import type {
  ParsedSseEvent,
  PlaygroundPageState,
  PlaygroundRequest,
  PlaygroundRunState,
} from "./state.js";
import {
  applyPlainResponse,
  buildGatewayHeaders,
  extractTokenUsage,
  extractAssistantText,
  formatSseTranscript,
  isAbortError,
  mergeAssistantOutput,
  mergeTokenUsage,
  tryParseJson,
} from "./serializers.js";
import { createEmptyTokenUsage } from "./state.js";

interface StreamFailureDetails {
  errorType: string;
  message: string;
  statusCode: number | null;
}

interface ExecutePlaygroundRequestOptions {
  gatewayKey: string;
  isCurrentRender: (token: number) => boolean;
  onUpdate: () => void;
  request: PlaygroundRequest;
  state: PlaygroundPageState;
  token: number;
}

export function abortPlaygroundRequest(state: PlaygroundPageState): void {
  state.activeController?.abort();
}

export function disposePlaygroundRequestState(state: PlaygroundPageState): void {
  state.activeRunId += 1;
  state.activeController?.abort();
  state.activeController = null;
}

export async function executePlaygroundRequest(
  options: ExecutePlaygroundRequestOptions,
): Promise<void> {
  const { gatewayKey, isCurrentRender, onUpdate, request, state, token } = options;

  state.activeRunId += 1;
  const runId = state.activeRunId;
  state.activeController?.abort();
  state.activeController = new AbortController();
  state.streamEvents.length = 0;
  Object.assign(state.runState, {
    phase: "sending",
    note: `Sending ${request.stream ? "streaming" : "plain"} request to ${request.url}.`,
    request,
    startedAt: performance.now(),
    finishedAt: null,
    statusCode: null,
    statusText: "",
    contentType: "",
    bytesReceived: 0,
    chunkCount: 0,
    eventCount: 0,
    tokenUsage: createEmptyTokenUsage(),
    assistantOutput: "",
    rawOutput: "",
    errorText: "",
  } satisfies PlaygroundRunState);
  onUpdate();

  try {
    const response = await fetch(request.url, {
      method: "POST",
      headers: buildGatewayHeaders(request.surface, gatewayKey, request.stream),
      body: JSON.stringify(request.body),
      signal: state.activeController.signal,
    });

    if (!isCurrentRender(token) || runId !== state.activeRunId) {
      return;
    }

    state.runState.statusCode = response.status;
    state.runState.statusText = response.statusText;
    state.runState.contentType = response.headers.get("content-type") ?? "";

    const shouldConsumeStream = shouldConsumeStreamResponse(response, request.stream);
    if (shouldConsumeStream) {
      state.runState.phase = "streaming";
      state.runState.note = state.runState.contentType.includes("text/event-stream")
        ? "Stream opened. Waiting for events…"
        : "Stream requested and a chunked response started without an SSE content-type. Parsing as a stream.";
      onUpdate();
      await consumeStreamResponse(
        response,
        request,
        state,
        () => {
          if (!isCurrentRender(token) || runId !== state.activeRunId) {
            return;
          }
          onUpdate();
        },
        state.activeController.signal,
      );
    } else {
      const rawText = await response.text();
      if (!isCurrentRender(token) || runId !== state.activeRunId) {
        return;
      }
      state.runState.bytesReceived = new Blob([rawText]).size;
      state.runState.chunkCount = rawText ? 1 : 0;
      applyPlainResponse(rawText, request, state.runState);
      if (request.stream) {
        state.runState.note =
          "Stream was requested, but the gateway returned a regular response body instead of SSE.";
      }
    }

    if (!isCurrentRender(token) || runId !== state.activeRunId) {
      return;
    }

    state.runState.finishedAt = performance.now();
    if (!response.ok) {
      state.runState.phase = "error";
      state.runState.errorText = `HTTP ${response.status}${response.statusText ? ` ${response.statusText}` : ""}`;
      state.runState.note =
        "Gateway returned a non-2xx response. Check parsed output, transport body, or bootstrap hints.";
    } else if (state.runState.phase === "error") {
      state.runState.note =
        state.runState.note ||
        "Stream reported an error event. Check parsed output and transport transcript.";
    } else if (state.runState.phase !== "aborted") {
      state.runState.phase = "success";
      state.runState.note = request.stream
        ? `Stream finished cleanly with ${state.runState.eventCount} event${state.runState.eventCount === 1 ? "" : "s"}.`
        : "Request completed successfully.";
    }
  } catch (error) {
    if (!isCurrentRender(token) || runId !== state.activeRunId) {
      return;
    }

    state.runState.finishedAt = performance.now();
    if (isAbortError(error)) {
      state.runState.phase = "aborted";
      state.runState.note = "Request aborted. You can adjust the payload and send again.";
    } else {
      state.runState.phase = "error";
      state.runState.errorText = toErrorMessage(error);
      state.runState.note = "Transport error before a complete response was received.";
    }
  } finally {
    if (runId === state.activeRunId) {
      state.activeController = null;
    }
    onUpdate();
  }
}

async function consumeStreamResponse(
  response: Response,
  request: PlaygroundRequest,
  state: PlaygroundPageState,
  onUpdate: () => void,
  signal: AbortSignal,
): Promise<void> {
  if (!response.body) {
    const fallback = await response.text();
    state.runState.bytesReceived = new Blob([fallback]).size;
    state.runState.chunkCount = fallback ? 1 : 0;
    applyPlainResponse(fallback, request, state.runState);
    return;
  }

  await readSseStream(
    response.body,
    {
      onChunk: (bytes) => {
        state.runState.bytesReceived += bytes;
        state.runState.chunkCount += 1;
      },
      onEvent: (event) => {
        state.streamEvents.push(event);
        state.runState.eventCount = state.streamEvents.length;
        state.runState.rawOutput = formatSseTranscript(state.streamEvents);
        if (event.data === "[DONE]") {
          state.runState.note =
            state.runState.phase === "error"
              ? "Received stream terminator after an error event."
              : "Received stream terminator.";
          onUpdate();
          return;
        }

        const payload = tryParseJson(event.data);
        const failure = extractStreamFailure(event, payload);
        if (failure !== null) {
          state.runState.phase = "error";
          state.runState.errorText = formatStreamFailure(failure);
          if (failure.statusCode !== null) {
            state.runState.statusCode = failure.statusCode;
            state.runState.statusText = failure.errorType;
          }
          state.runState.note = `Stream emitted ${failure.errorType} after ${state.runState.eventCount} event${state.runState.eventCount === 1 ? "" : "s"}.`;
        }
        state.runState.tokenUsage = mergeTokenUsage(
          state.runState.tokenUsage,
          payload === null ? null : extractTokenUsage(payload),
        );
        const textDelta = payload === null ? event.data : extractAssistantText(payload, request.surface);
        state.runState.assistantOutput = mergeAssistantOutput(
          state.runState.assistantOutput,
          textDelta,
          event.type,
          payload,
          request.surface,
        );
        if (failure === null) {
          state.runState.note = `Streaming… ${state.runState.eventCount} event${state.runState.eventCount === 1 ? "" : "s"} parsed.`;
        }
        onUpdate();
      },
    },
    signal,
  );
}

function shouldConsumeStreamResponse(
  response: Response,
  streamRequested: boolean,
): boolean {
  const contentType = response.headers.get("content-type")?.toLowerCase() ?? "";
  return contentType.includes("text/event-stream") || (streamRequested && response.ok);
}

function extractStreamFailure(
  event: ParsedSseEvent,
  payload: unknown,
): StreamFailureDetails | null {
  const payloadRecord =
    payload && typeof payload === "object" && !Array.isArray(payload)
      ? (payload as Record<string, unknown>)
      : null;
  const errorRecord =
    payloadRecord?.error && typeof payloadRecord.error === "object" && !Array.isArray(payloadRecord.error)
      ? (payloadRecord.error as Record<string, unknown>)
      : null;
  const eventType = event.type.trim().toLowerCase();
  const failureRecord =
    errorRecord ?? (eventType === "error" && payloadRecord !== null ? payloadRecord : null);

  if (failureRecord === null && eventType !== "error") {
    return null;
  }

  const message =
    typeof failureRecord?.message === "string" && failureRecord.message.trim()
      ? failureRecord.message.trim()
      : event.data.trim();
  const errorType =
    typeof failureRecord?.type === "string" && failureRecord.type.trim()
      ? failureRecord.type.trim()
      : typeof failureRecord?.code === "string" && failureRecord.code.trim()
        ? failureRecord.code.trim()
      : eventType === "error"
        ? "stream_error"
        : "error";
  const parsedStatusCode = normalizeStatusCode(failureRecord?.status_code);

  return {
    errorType,
    message,
    statusCode: parsedStatusCode ?? inferStatusCodeFromText(message),
  };
}

function normalizeStatusCode(value: unknown): number | null {
  const numeric = Number(value);
  if (!Number.isInteger(numeric) || numeric < 100 || numeric > 599) {
    return null;
  }
  return numeric;
}

function inferStatusCodeFromText(message: string): number | null {
  const match = message.match(/(^|\\D)([1-5]\\d{2})(?=\\D|$)/u);
  if (!match) {
    return null;
  }
  return normalizeStatusCode(match[2]);
}

function formatStreamFailure(failure: StreamFailureDetails): string {
  const message = failure.message.trim();
  if (!message) {
    return failure.statusCode === null
      ? failure.errorType
      : `${failure.errorType}: ${failure.statusCode}`;
  }
  return message.startsWith(`${failure.errorType}:`)
    ? message
    : `${failure.errorType}: ${message}`;
}

async function readSseStream(
  stream: ReadableStream<Uint8Array>,
  handlers: {
    onChunk: (bytes: number) => void;
    onEvent: (event: ParsedSseEvent) => void;
  },
  signal?: AbortSignal,
): Promise<void> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const abortReader = (): void => {
    void reader.cancel().catch(() => {
      // Ignore cancellation races after the stream has already closed.
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
        flushSseFrames(buffer, handlers.onEvent);
        return;
      }

      handlers.onChunk(value.byteLength);
      buffer += decoder.decode(value, { stream: true });
      const frames = buffer.split(/\r?\n\r?\n/u);
      buffer = frames.pop() ?? "";
      frames.forEach((frame) => flushSseFrames(frame, handlers.onEvent));
    }
  } finally {
    signal?.removeEventListener("abort", abortReader);
    reader.releaseLock();
  }
}

function flushSseFrames(rawFrame: string, onEvent: (event: ParsedSseEvent) => void): void {
  const frame = rawFrame.trim();
  if (!frame) {
    return;
  }

  let eventType = "message";
  const dataLines: string[] = [];
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

  if (!dataLines.length && eventType === "message") {
    return;
  }

  onEvent({
    type: eventType,
    data: dataLines.join("\n"),
  });
}
