export type MessageActionKind = "copy" | "edit";

export interface ResolvedMessageAction {
  content: string;
  kind: MessageActionKind;
}

type TimelineMessage = {
  edited_from_message_id?: string;
  id: string;
  role: string;
};

export function projectActiveMessageTimeline<T extends TimelineMessage>(
  messages: readonly T[],
): T[] {
  const active: T[] = [];
  for (const item of messages) {
    if (item.edited_from_message_id) {
      const sourceIndex = active.findIndex(
        (candidate) => candidate.id === item.edited_from_message_id,
      );
      if (sourceIndex >= 0) active.splice(sourceIndex);
    }
    active.push(item);
  }
  return active;
}

export function latestEditableUserMessageId(
  messages: readonly TimelineMessage[],
): string | undefined {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const item = messages[index];
    if (item?.role === "user") return item.id;
  }
  return undefined;
}

export function timelineWhileEditing<T extends TimelineMessage>(
  messages: readonly T[],
  messageId: string | undefined,
): T[] {
  if (messageId === undefined) return [...messages];
  const sourceIndex = messages.findIndex((item) => item.id === messageId);
  return sourceIndex < 0 ? [...messages] : messages.slice(0, sourceIndex + 1);
}

export async function resolveMessageAction(
  kind: MessageActionKind,
  loadContent: () => Promise<string>,
  writeClipboard: (content: string) => Promise<void>,
): Promise<ResolvedMessageAction> {
  const content = await loadContent();
  if (kind === "copy") await writeClipboard(content);
  return { content, kind };
}
