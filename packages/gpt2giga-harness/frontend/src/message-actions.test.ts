import { describe, expect, it, vi } from "vitest";

import { resolveMessageAction } from "./message-actions";

describe("message actions", () => {
  it("copies the complete fetched assistant message instead of its bounded preview", async () => {
    const full = `prefix\n${"x".repeat(40_000)}\nsuffix`;
    const writeClipboard = vi.fn(async () => undefined);

    const resolved = await resolveMessageAction(
      "copy",
      async () => full,
      writeClipboard,
    );

    expect(writeClipboard).toHaveBeenCalledOnce();
    expect(writeClipboard).toHaveBeenCalledWith(full);
    expect(resolved).toEqual({ content: full, kind: "copy" });
  });

  it("returns the complete user message for editing without touching the clipboard", async () => {
    const writeClipboard = vi.fn(async () => undefined);

    const resolved = await resolveMessageAction(
      "edit",
      async () => "  keep whitespace\nfor the next turn  ",
      writeClipboard,
    );

    expect(writeClipboard).not.toHaveBeenCalled();
    expect(resolved).toEqual({
      content: "  keep whitespace\nfor the next turn  ",
      kind: "edit",
    });
  });
});
