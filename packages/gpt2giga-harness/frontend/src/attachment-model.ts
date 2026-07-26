import type { AttachmentSummary, MessageProjection } from "./api";

export function composerAttachments(
  attachments: readonly AttachmentSummary[],
  messages: readonly MessageProjection[],
): AttachmentSummary[] {
  const retainedIds = new Set(
    messages.flatMap((message) => (
      message.attachments?.map((attachment) => attachment.id) ?? []
    )),
  );
  return attachments.filter((attachment) => !retainedIds.has(attachment.id));
}

export function isPreviewableImage(
  attachment: AttachmentSummary,
): attachment is AttachmentSummary & { url: string } {
  return attachment.url !== undefined && attachment.mime_type?.startsWith("image/") === true;
}
