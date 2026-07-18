import { describe, expect, it, vi } from "vitest";

import {
  latestEditableUserMessageId,
  projectActiveMessageTimeline,
  resolveMessageAction,
  timelineWhileEditing,
} from "./message-actions";

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

  it("keeps only the latest user message editable", () => {
    const messages = [
      { id: "user-1", role: "user" },
      { id: "assistant-1", role: "assistant" },
      { id: "user-2", role: "user" },
      { id: "assistant-2", role: "assistant" },
    ];

    expect(latestEditableUserMessageId(messages)).toBe("user-2");
  });

  it("removes the edited user turn and following assistant from the active timeline", () => {
    const messages = [
      { id: "user-1", role: "user" },
      { id: "assistant-1", role: "assistant" },
      { id: "user-2", role: "user" },
      { id: "assistant-2", role: "assistant" },
      { edited_from_message_id: "user-2", id: "user-3", role: "user" },
      { id: "assistant-3", role: "assistant" },
    ];

    expect(projectActiveMessageTimeline(messages).map((item) => item.id)).toEqual([
      "user-1",
      "assistant-1",
      "user-3",
      "assistant-3",
    ]);
    expect(
      timelineWhileEditing(projectActiveMessageTimeline(messages), "user-3")
        .map((item) => item.id),
    ).toEqual(["user-1", "assistant-1", "user-3"]);
  });
});
