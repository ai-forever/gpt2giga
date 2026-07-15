import { describe, expect, it, vi } from "vitest";

import {
  RunEventStreamStore,
  coalescePresentationDeltas,
  type RunStreamEvent,
} from "./stream-store";

function event(id: string, type = "message_delta", delta = id): RunStreamEvent {
  return {
    id,
    payload: { delta },
    run_id: "run-one",
    type,
  };
}

describe("run event stream store", () => {
  it("batches normal deltas per frame and prioritizes terminal control", () => {
    const frames: Array<() => void> = [];
    const store = new RunEventStreamStore({
      scheduleFrame: (callback) => {
        frames.push(callback);
        return vi.fn();
      },
    });

    store.ingest(event("one", "message_delta", "A"));
    store.ingest(event("two", "message_delta", "B"));
    expect(store.getSnapshot().events).toHaveLength(0);
    store.ingest(event("finished", "run_finished"));

    expect(store.getSnapshot().events.map((item) => item.type)).toEqual([
      "message_delta",
      "run_finished",
    ]);
    expect(store.getSnapshot().events.at(0)?.payload?.delta).toBe("AB");
    expect(store.getSnapshot().events.at(0)?.coalesced_ids).toEqual([
      "one",
      "two",
    ]);
    expect(store.getSnapshot().status).toBe("closed");
  });

  it("deduplicates reconnect replay and bounds the retained render window", () => {
    const frames: Array<() => void> = [];
    const store = new RunEventStreamStore({
      maxEvents: 2,
      scheduleFrame: (callback) => {
        frames.push(callback);
        return vi.fn();
      },
    });
    for (const item of [
      event("one", "usage"),
      event("one", "usage"),
      event("two", "file_changed"),
      event("three", "test_completed"),
    ]) {
      store.ingest(item);
    }
    while (frames.length > 0) frames.shift()?.();

    expect(store.getSnapshot().events.map((item) => item.id)).toEqual([
      "two",
      "three",
    ]);
    expect(store.getSnapshot().windowTruncated).toBe(true);
  });

  it("coalesces only safe presentation deltas", () => {
    const events = coalescePresentationDeltas([
      event("one", "message_delta", "A"),
      event("two", "message_delta", "B"),
      event("tool", "tool_call_started", "ignored"),
    ]);

    expect(events).toHaveLength(2);
    expect(events.at(0)?.payload?.delta).toBe("AB");
    expect(events.at(1)?.id).toBe("tool");
  });

  it("surfaces an explicit slow-consumer resnapshot and cleans up", () => {
    const listeners = new Map<string, (event: { data: string }) => void>();
    const close = vi.fn();
    const source: {
      addEventListener: (
        name: string,
        listener: (event: { data: string }) => void,
      ) => void;
      close: () => void;
      onerror: ((event: Event) => void) | null;
      onmessage: ((event: { data: string }) => void) | null;
      onopen: ((event: Event) => void) | null;
    } = {
      addEventListener: (
        name: string,
        listener: (event: { data: string }) => void,
      ) => listeners.set(name, listener),
      close,
      onerror: null,
      onmessage: null,
      onopen: null,
    };
    const store = new RunEventStreamStore({
      createEventSource: () => source,
    });

    const cleanup = store.connect("run one");
    source.onopen?.(new Event("open"));
    listeners.get("resnapshot")?.({
      data: JSON.stringify({
        snapshot_url: "/api/cockpit/sessions/session-one/events",
      }),
    });

    expect(store.getSnapshot().status).toBe("resnapshot_required");
    expect(store.getSnapshot().resnapshotUrl).toBe(
      "/api/cockpit/sessions/session-one/events",
    );
    cleanup();
    expect(close).toHaveBeenCalledOnce();
  });
});
