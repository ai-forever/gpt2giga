import { describe, expect, it } from "vitest";

import { generatedImageProjection } from "./generated-image";

describe("generatedImageProjection", () => {
  it("accepts only retained Harness generated-file previews", () => {
    expect(generatedImageProjection({
      filename: "result.png",
      mime_type: "image/png",
      preview_url: "/api/files/generated/run/image.png",
      size_bytes: 2048,
    })).toEqual({
      filename: "result.png",
      mimeType: "image/png",
      previewUrl: "/api/files/generated/run/image.png",
      sizeBytes: 2048,
    });
    expect(generatedImageProjection({ preview_url: "https://example.test/image.png" })).toBeNull();
    expect(generatedImageProjection({ preview_url: "javascript:alert(1)" })).toBeNull();
  });
});
