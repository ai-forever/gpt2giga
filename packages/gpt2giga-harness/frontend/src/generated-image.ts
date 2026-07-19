export interface GeneratedFileProjection {
  downloadUrl: string;
  filename: string;
  isImage: boolean;
  mimeType: string;
  previewUrl: string | null;
  sizeBytes: number | null;
}

export function generatedFileProjection(
  payload?: Readonly<Record<string, unknown>>,
): GeneratedFileProjection | null {
  const previewUrl = typeof payload?.preview_url === "string" ? payload.preview_url : null;
  if (previewUrl !== null && !previewUrl.startsWith("/api/files/generated/")) return null;
  const filename = typeof payload?.filename === "string" ? payload.filename : "Generated file";
  const explicitDownloadUrl = typeof payload?.download_url === "string"
    ? payload.download_url
    : null;
  const downloadUrl = explicitDownloadUrl
    ?? (previewUrl === null ? "" : `${previewUrl}?download=${encodeURIComponent(filename)}`);
  if (!downloadUrl.startsWith("/api/files/generated/")) return null;
  const mimeType = typeof payload?.mime_type === "string"
    ? payload.mime_type
    : "application/octet-stream";
  const isImage = mimeType.startsWith("image/") && previewUrl !== null;
  return {
    downloadUrl,
    filename,
    isImage,
    mimeType,
    previewUrl,
    sizeBytes: typeof payload?.size_bytes === "number" ? payload.size_bytes : null,
  };
}
