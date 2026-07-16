import { useEffect, useRef, useSyncExternalStore } from "react";

export type RunStreamStatus =
  | "idle"
  | "connecting"
  | "live"
  | "reconnecting"
  | "resnapshot_required"
  | "closed";

export interface RunStreamEvent {
  id: string;
  run_id: string;
  type: string;
  message?: string;
  payload?: Readonly<Record<string, unknown>>;
  created_at?: string;
  coalesced_ids?: readonly string[];
}

export interface RunStreamSnapshot {
  runId: string | null;
  status: RunStreamStatus;
  events: readonly RunStreamEvent[];
  windowTruncated: boolean;
  resnapshotUrl: string | null;
}

interface MessageEventLike {
  data: string;
}

interface EventSourceLike {
  onopen: ((event: Event) => void) | null;
  onmessage: ((event: MessageEventLike) => void) | null;
  onerror: ((event: Event) => void) | null;
  addEventListener(
    name: string,
    listener: (event: MessageEventLike) => void,
  ): void;
  close(): void;
}

type EventSourceFactory = (url: string) => EventSourceLike;
type FrameScheduler = (callback: () => void) => () => void;

const CONTROL_EVENT_TYPES = new Set([
  "approval_requested",
  "approval_decided",
  "cancel_requested",
  "error",
  "policy_allowed",
  "policy_denied",
  "run_canceled",
  "run_finished",
  "tool_call_finished",
  "tool_call_started",
  "warning",
]);
const COALESCIBLE_EVENT_TYPES = new Set([
  "message_delta",
  "reasoning_delta",
  "stderr_delta",
  "stdout_delta",
  "tool_call_delta",
]);

const defaultFrameScheduler: FrameScheduler = (callback) => {
  if (typeof globalThis.requestAnimationFrame === "function") {
    const handle = globalThis.requestAnimationFrame(callback);
    return () => globalThis.cancelAnimationFrame(handle);
  }
  const handle = globalThis.setTimeout(callback, 16);
  return () => globalThis.clearTimeout(handle);
};

const defaultEventSourceFactory: EventSourceFactory = (url) =>
  new EventSource(url) as unknown as EventSourceLike;

const idleSnapshot: RunStreamSnapshot = {
  runId: null,
  status: "idle",
  events: [],
  windowTruncated: false,
  resnapshotUrl: null,
};

export class RunEventStreamStore {
  private readonly maxEvents: number;
  private readonly maxPendingEvents: number;
  private readonly scheduleFrame: FrameScheduler;
  private readonly createEventSource: EventSourceFactory;
  private readonly listeners = new Set<() => void>();
  private readonly seenIds = new Set<string>();
  private pending: RunStreamEvent[] = [];
  private cancelFrame: (() => void) | null = null;
  private source: EventSourceLike | null = null;
  private snapshot: RunStreamSnapshot = idleSnapshot;

  constructor(
    options: {
      maxEvents?: number;
      maxPendingEvents?: number;
      scheduleFrame?: FrameScheduler;
      createEventSource?: EventSourceFactory;
    } = {},
  ) {
    this.maxEvents = Math.max(1, options.maxEvents ?? 500);
    this.maxPendingEvents = Math.max(1, options.maxPendingEvents ?? 512);
    this.scheduleFrame = options.scheduleFrame ?? defaultFrameScheduler;
    this.createEventSource =
      options.createEventSource ?? defaultEventSourceFactory;
  }

  readonly subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  readonly getSnapshot = (): RunStreamSnapshot => this.snapshot;

  connect(runId: string, tailOnly = true): () => void {
    this.disconnect();
    this.seenIds.clear();
    this.pending = [];
    this.setSnapshot({
      runId,
      status: "connecting",
      events: [],
      windowTruncated: false,
      resnapshotUrl: null,
    });
    const source = this.createEventSource(
      `/api/runs/${encodeURIComponent(runId)}/events/stream?tail_only=${tailOnly}`,
    );
    this.source = source;
    source.onopen = () => {
      if (this.source === source) this.patchSnapshot({ status: "live" });
    };
    source.onmessage = (message) => {
      if (this.source !== source) return;
      const event = parseRunStreamEvent(message.data);
      if (event !== null) this.ingest(event);
    };
    source.addEventListener("resnapshot", (message) => {
      if (this.source !== source) return;
      const payload = parseObject(message.data);
      this.flushPending();
      this.patchSnapshot({
        status: "resnapshot_required",
        resnapshotUrl:
          typeof payload?.snapshot_url === "string"
            ? payload.snapshot_url
            : null,
      });
    });
    source.onerror = () => {
      if (this.source === source && this.snapshot.status !== "closed") {
        this.patchSnapshot({ status: "reconnecting" });
      }
    };
    return () => {
      if (this.source === source) this.disconnect();
    };
  }

  disconnect(): void {
    this.source?.close();
    this.source = null;
    this.cancelFrame?.();
    this.cancelFrame = null;
    this.pending = [];
    if (this.snapshot.runId !== null && this.snapshot.status !== "closed") {
      this.patchSnapshot({ status: "closed" });
    }
  }

  ingest(event: RunStreamEvent): void {
    if (!event.id || this.seenIds.has(event.id)) return;
    this.seenIds.add(event.id);
    if (isControlEvent(event.type)) {
      this.flushPending();
      this.appendEvents([event]);
      if (event.type === "run_finished" || event.type === "run_canceled") {
        this.source?.close();
        this.source = null;
        this.patchSnapshot({ status: "closed" });
      }
      return;
    }
    this.pending.push(event);
    if (this.pending.length > this.maxPendingEvents) {
      this.pending = coalescePresentationDeltas(this.pending);
      if (this.pending.length > this.maxPendingEvents) {
        this.pending = this.pending.slice(-this.maxPendingEvents);
        this.patchSnapshot({ status: "resnapshot_required" });
      }
    }
    if (this.cancelFrame === null) {
      this.cancelFrame = this.scheduleFrame(() => {
        this.cancelFrame = null;
        this.flushPending();
      });
    }
  }

  private flushPending(): void {
    this.cancelFrame?.();
    this.cancelFrame = null;
    if (this.pending.length === 0) return;
    const events = coalescePresentationDeltas(this.pending);
    this.pending = [];
    this.appendEvents(events);
  }

  private appendEvents(events: readonly RunStreamEvent[]): void {
    const combined = [...this.snapshot.events, ...events];
    const truncated = combined.length > this.maxEvents;
    this.patchSnapshot({
      events: truncated ? combined.slice(-this.maxEvents) : combined,
      windowTruncated: this.snapshot.windowTruncated || truncated,
    });
  }

  private patchSnapshot(patch: Partial<RunStreamSnapshot>): void {
    this.setSnapshot({ ...this.snapshot, ...patch });
  }

  private setSnapshot(snapshot: RunStreamSnapshot): void {
    this.snapshot = snapshot;
    for (const listener of this.listeners) listener();
  }
}

export function useRunEventStream(
  runId: string | undefined,
  resetToken = 0,
  tailOnly = true,
): RunStreamSnapshot {
  const storeRef = useRef<RunEventStreamStore | null>(null);
  if (storeRef.current === null) storeRef.current = new RunEventStreamStore();
  const store = storeRef.current;
  useEffect(() => {
    if (runId === undefined || typeof globalThis.EventSource !== "function") {
      store.disconnect();
      return;
    }
    return store.connect(runId, tailOnly);
  }, [resetToken, runId, store, tailOnly]);
  return useSyncExternalStore(
    store.subscribe,
    store.getSnapshot,
    () => idleSnapshot,
  );
}

export function coalescePresentationDeltas(
  events: readonly RunStreamEvent[],
): RunStreamEvent[] {
  const result: RunStreamEvent[] = [];
  for (const event of events) {
    const previous = result.at(-1);
    const previousDelta = previous?.payload?.delta;
    const eventDelta = event.payload?.delta;
    if (
      previous !== undefined &&
      previous.type === event.type &&
      previous.run_id === event.run_id &&
      COALESCIBLE_EVENT_TYPES.has(event.type) &&
      typeof previousDelta === "string" &&
      typeof eventDelta === "string"
    ) {
      result[result.length - 1] = {
        ...event,
        payload: { ...event.payload, delta: previousDelta + eventDelta },
        coalesced_ids: [
          ...(previous.coalesced_ids ?? [previous.id]),
          event.id,
        ],
      };
    } else {
      result.push(event);
    }
  }
  return result;
}

function isControlEvent(type: string): boolean {
  return CONTROL_EVENT_TYPES.has(type) || type.startsWith("policy_");
}

function parseRunStreamEvent(value: string): RunStreamEvent | null {
  const payload = parseObject(value);
  if (
    payload === null ||
    typeof payload.id !== "string" ||
    typeof payload.run_id !== "string" ||
    typeof payload.type !== "string"
  ) {
    return null;
  }
  return payload as unknown as RunStreamEvent;
}

function parseObject(value: string): Record<string, unknown> | null {
  try {
    const payload: unknown = JSON.parse(value);
    return payload !== null && typeof payload === "object"
      ? (payload as Record<string, unknown>)
      : null;
  } catch {
    return null;
  }
}
