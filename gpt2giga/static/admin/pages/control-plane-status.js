import { summarizePendingChanges } from "../forms.js";
import { banner, renderControlPlaneSectionStatus } from "../templates.js";
export function renderControlPlaneStatusNode(node, options) {
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
export function renderInlineBannerStatus(node, actionState, idleMessage) {
    if (!node) {
        return;
    }
    node.innerHTML = actionState
        ? banner(actionState.message, actionState.tone)
        : banner(idleMessage);
}
export function collectSecretFieldMessages(states) {
    return states
        .filter((state) => Boolean(state))
        .filter((state) => state.intent !== "keep")
        .map((state) => state.message);
}
