export interface GeneratedImageProjection {
  filename: string;
  mimeType: string;
  previewUrl: string;
  sizeBytes: number | null;
}

export function generatedImageProjection(
  payload?: Readonly<Record<string, unknown>>,
): GeneratedImageProjection | null {
  const previewUrl = typeof payload?.preview_url === "string" ? payload.preview_url : "";
  if (!previewUrl.startsWith("/api/files/generated/")) return null;
  return {
    filename: typeof payload?.filename === "string" ? payload.filename : "Generated image",
    mimeType: typeof payload?.mime_type === "string" ? payload.mime_type : "image/jpeg",
    previewUrl,
    sizeBytes: typeof payload?.size_bytes === "number" ? payload.size_bytes : null,
  };
}
