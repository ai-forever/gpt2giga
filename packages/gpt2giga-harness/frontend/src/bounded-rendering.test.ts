import { describe, expect, it, vi } from "vitest";

import {
  computeVirtualWindow,
  markdownChunks,
  preserveScrollAnchor,
  renderTextIncrementally,
} from "./bounded-rendering";

describe("bounded rendering primitives", () => {
  it("renders only an overscanned virtual window", () => {
    expect(
      computeVirtualWindow({
        estimatedItemHeight: 40,
        itemCount: 50_000,
        overscan: 3,
        scrollTop: 4_000,
        viewportHeight: 800,
      }),
    ).toEqual({
      start: 97,
      end: 123,
      offsetTop: 3_880,
      totalHeight: 2_000_000,
    });
  });

  it("preserves a reader's scroll anchor when older rows prepend", () => {
    expect(
      preserveScrollAnchor({
        insertedHeight: 240,
        pinnedToEnd: false,
        scrollTop: 640,
      }),
    ).toBe(880);
  });

  it("splits markdown and schedules one bounded chunk at a time", () => {
    const callbacks: Array<() => void> = [];
    const received: string[] = [];
    const cancel = renderTextIncrementally(
      `first\n${"x".repeat(600)}\nlast`,
      (chunk) => received.push(chunk),
      {
        maxCharacters: 256,
        schedule: (callback) => {
          callbacks.push(callback);
          return vi.fn();
        },
      },
    );

    expect(markdownChunks("short", 256)).toEqual(["short"]);
    expect(received).toEqual([]);
    while (callbacks.length > 0) callbacks.shift()?.();
    expect(received.join("")).toBe(`first\n${"x".repeat(600)}\nlast`);
    expect(received.length).toBeGreaterThan(1);
    cancel();
  });
});
