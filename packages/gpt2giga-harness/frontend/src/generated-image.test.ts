import { describe, expect, it } from "vitest";

import { generatedFileProjection } from "./generated-image";

describe("generatedFileProjection", () => {
  it("accepts only retained Harness generated-file URLs", () => {
    expect(generatedFileProjection({
      download_url: "/api/files/generated/run/image.png?download=result.png",
      filename: "result.png",
      mime_type: "image/png",
      preview_url: "/api/files/generated/run/image.png",
      size_bytes: 2048,
    })).toEqual({
      downloadUrl: "/api/files/generated/run/image.png?download=result.png",
      filename: "result.png",
      isImage: true,
      mimeType: "image/png",
      previewUrl: "/api/files/generated/run/image.png",
      sizeBytes: 2048,
    });
    expect(generatedFileProjection({
      download_url: "/api/files/generated/run/report.html?download=report.html",
      filename: "report.html",
      mime_type: "text/html",
      size_bytes: 4096,
    })).toEqual({
      downloadUrl: "/api/files/generated/run/report.html?download=report.html",
      filename: "report.html",
      isImage: false,
      mimeType: "text/html",
      previewUrl: null,
      sizeBytes: 4096,
    });
    expect(generatedFileProjection({ download_url: "https://example.test/file" })).toBeNull();
    expect(generatedFileProjection({ download_url: "javascript:alert(1)" })).toBeNull();
  });

  it("keeps retained generated images from before download URLs were persisted", () => {
    expect(generatedFileProjection({
      filename: "legacy image.jpg",
      mime_type: "image/jpeg",
      preview_url: "/api/files/generated/run/image.jpg",
    })?.downloadUrl).toBe(
      "/api/files/generated/run/image.jpg?download=legacy%20image.jpg",
    );
  });
});
