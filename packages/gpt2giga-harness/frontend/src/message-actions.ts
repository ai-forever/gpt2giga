export type MessageActionKind = "copy" | "edit";

export interface ResolvedMessageAction {
  content: string;
  kind: MessageActionKind;
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
