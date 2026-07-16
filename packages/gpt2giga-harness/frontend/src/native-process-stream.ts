import type { NativeOutputResponse } from "./api";

interface MessageEventLike {
  data: string;
}

interface EventSourceLike {
  onmessage: ((event: MessageEventLike) => void) | null;
  close(): void;
}

type EventSourceFactory = (url: string) => EventSourceLike;

const defaultEventSourceFactory: EventSourceFactory = (url) =>
  new EventSource(url) as unknown as EventSourceLike;

export function observeNativeProcess(
  processId: string,
  onUpdate: (payload: NativeOutputResponse) => void,
  createEventSource: EventSourceFactory = defaultEventSourceFactory,
): () => void {
  const source = createEventSource(
    `/api/native/processes/${encodeURIComponent(processId)}/output/stream`,
  );
  source.onmessage = (message) => {
    const payload = parseNativeOutput(message.data);
    if (payload === null) return;
    onUpdate(payload);
    const status = payload.status ?? payload.process?.status;
    if (payload.terminal === true || (status !== undefined && status !== "running")) {
      source.close();
    }
  };
  return () => source.close();
}

function parseNativeOutput(value: string): NativeOutputResponse | null {
  try {
    const payload = JSON.parse(value) as Partial<NativeOutputResponse>;
    return typeof payload.cursor === "number"
      ? payload as NativeOutputResponse
      : null;
  } catch {
    return null;
  }
}
