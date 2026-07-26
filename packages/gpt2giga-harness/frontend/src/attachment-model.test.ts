import { describe, expect, it } from "vitest";

import type { AttachmentSummary, MessageProjection } from "./api";
import { composerAttachments, isPreviewableImage } from "./attachment-model";

const image: AttachmentSummary = {
  id: "att-image",
  filename: "screen.png",
  kind: "image",
  mime_type: "image/png",
  size_bytes: 2048,
  url: "/api/attachments/att-image",
};

describe("composerAttachments", () => {
  it("keeps unsent uploads and removes retained message attachments", () => {
    const document: AttachmentSummary = {
      id: "att-document",
      filename: "brief.pdf",
      mime_type: "application/pdf",
      size_bytes: 1024,
      url: "/api/attachments/att-document",
    };
    const messages = [{
      id: "msg-user",
      role: "user",
      created_at: "2026-07-24T00:00:00Z",
      content: { text: "look", byte_count: 4, truncated: false },
      attachments: [image],
    }] satisfies MessageProjection[];

    expect(composerAttachments([image, document], messages)).toEqual([document]);
  });
});

describe("isPreviewableImage", () => {
  it("requires both an image mime type and a retained blob URL", () => {
    expect(isPreviewableImage(image)).toBe(true);
    expect(isPreviewableImage({ ...image, url: undefined })).toBe(false);
    expect(isPreviewableImage({ ...image, mime_type: "application/pdf" })).toBe(false);
  });
});
