import { describe, expect, it, vi } from "vitest";

import { observeNativeProcess } from "./native-process-stream";

describe("native process stream", () => {
  it("uses the retained output stream and ignores malformed payloads", () => {
    const close = vi.fn();
    const source = { close, onmessage: null as ((event: { data: string }) => void) | null };
    const update = vi.fn();
    let url = "";
    const cleanup = observeNativeProcess("proc one", update, (value) => {
      url = value;
      return source;
    });

    source.onmessage?.({ data: "not-json" });
    source.onmessage?.({ data: JSON.stringify({ cursor: 7, status: "running" }) });

    expect(url).toBe("/api/native/processes/proc%20one/output/stream");
    expect(update).toHaveBeenCalledOnce();
    expect(update.mock.calls[0]?.[0]).toMatchObject({ cursor: 7 });
    cleanup();
    expect(close).toHaveBeenCalledOnce();
  });
});
