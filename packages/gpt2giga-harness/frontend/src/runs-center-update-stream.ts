export interface RunsCenterUpdateEvent {
  revision: string;
  type: "runs.updated";
}

interface MessageEventLike {
  data: string;
}

interface EventSourceLike {
  onmessage: ((event: MessageEventLike) => void) | null;
  addEventListener(
    name: string,
    listener: (event: MessageEventLike) => void,
  ): void;
  close(): void;
}

type EventSourceFactory = (url: string) => EventSourceLike;

const defaultEventSourceFactory: EventSourceFactory = (url) =>
  new EventSource(url) as unknown as EventSourceLike;

export function observeRunsCenterUpdates(
  onRevision: (event: RunsCenterUpdateEvent | null) => void,
  createEventSource: EventSourceFactory = defaultEventSourceFactory,
): () => void {
  const source = createEventSource("/api/runs/updates/stream");
  source.onmessage = (message) => {
    const event = parseRunsCenterUpdate(message.data);
    if (event !== null) onRevision(event);
  };
  source.addEventListener("resnapshot", () => onRevision(null));
  return () => source.close();
}

function parseRunsCenterUpdate(value: string): RunsCenterUpdateEvent | null {
  try {
    const event = JSON.parse(value) as Partial<RunsCenterUpdateEvent>;
    if (event.type !== "runs.updated" || typeof event.revision !== "string") {
      return null;
    }
    return event as RunsCenterUpdateEvent;
  } catch {
    return null;
  }
}
