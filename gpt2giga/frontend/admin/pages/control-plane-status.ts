import type { SecretFieldState } from "../forms.js";
import type { DiffEntry } from "../types.js";
import { summarizePendingChanges } from "../forms.js";
import { banner, renderControlPlaneSectionStatus } from "../templates.js";
import type { InlineStatus } from "./control-plane-actions.js";

export function renderControlPlaneStatusNode(
  node: HTMLElement | null | undefined,
  options: {
    entries: DiffEntry[];
    persisted: boolean;
    updatedAt: unknown;
    note: string;
    validationMessage?: string;
    actionState: InlineStatus | null;
  },
): void {
  if (!node) {
    return;
  }

  node.innerHTML = renderControlPlaneSectionStatus({
    summary: summarizePendingChanges(options.entries),
    persisted: options.persisted,
    updatedAt: options.updatedAt,
    note: options.note,
    validationMessage: options.validationMessage,
    actionState: options.actionState,
  });
}

export function renderInlineBannerStatus(
  node: HTMLElement | null | undefined,
  actionState: InlineStatus | null,
  idleMessage: string,
): void {
  if (!node) {
    return;
  }

  node.innerHTML = actionState
    ? banner(actionState.message, actionState.tone)
    : banner(idleMessage);
}

export function collectSecretFieldMessages(
  states: Array<SecretFieldState | null>,
): string[] {
  return states
    .filter((state): state is SecretFieldState => Boolean(state))
    .filter((state) => state.intent !== "keep")
    .map((state) => state.message);
}
