import { renderControlPlaneStatusNode } from "./control-plane-status.js";
import { getSubmitterButton, persistControlPlaneSection, testGigachatConnection, } from "./control-plane-actions.js";
export function bindControlPlaneSectionForm(options) {
    let actionState = null;
    const dirtyStateKey = options.form.id || options.endpoint;
    const buildSnapshot = (report = false) => {
        const payload = options.buildPayload();
        return {
            payload,
            entries: options.buildEntries(payload),
            note: options.buildNote(payload),
            validationMessage: options.getValidationMessage?.(payload, report) ?? "",
        };
    };
    const refreshStatus = () => {
        const snapshot = buildSnapshot();
        options.app.setFormDirty(dirtyStateKey, snapshot.entries.length > 0);
        renderControlPlaneStatusNode(options.statusNode, {
            entries: snapshot.entries,
            persisted: options.persisted,
            updatedAt: options.updatedAt,
            note: snapshot.note,
            validationMessage: snapshot.validationMessage || undefined,
            actionState,
        });
    };
    options.form.addEventListener("input", refreshStatus);
    options.form.addEventListener("change", refreshStatus);
    options.form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const snapshot = buildSnapshot(true);
        options.app.setFormDirty(dirtyStateKey, snapshot.entries.length > 0);
        if (snapshot.validationMessage) {
            refreshStatus();
            options.onValidationError?.(snapshot.validationMessage);
            return;
        }
        await persistControlPlaneSection({
            app: options.app,
            form: options.form,
            button: getSubmitterButton(event, options.form),
            endpoint: options.endpoint,
            payload: snapshot.payload,
            refreshStatus,
            setActionState: (state) => {
                actionState = state;
            },
            pendingMessage: options.pendingMessage,
            pendingLabel: options.pendingLabel,
            outcomeLabel: options.outcomeLabel,
            failurePrefix: options.failurePrefix,
            rerenderPage: options.rerenderPage,
        });
    });
    options.app.registerCleanup(() => {
        options.app.setFormDirty(dirtyStateKey, false);
    });
    refreshStatus();
    return {
        refreshStatus,
        setActionState: (state) => {
            actionState = state;
        },
    };
}
export function bindGigachatConnectionTestAction(options) {
    if (!options.button) {
        return;
    }
    options.button.addEventListener("click", async () => {
        const payload = options.buildPayload();
        const validationMessage = options.getValidationMessage?.(payload, true) ?? "";
        if (validationMessage) {
            options.refreshStatus();
            options.onValidationError?.(validationMessage);
            return;
        }
        await testGigachatConnection({
            app: options.app,
            form: options.form,
            button: options.button,
            payload,
            refreshStatus: options.refreshStatus,
            setActionState: options.setActionState,
            pendingMessage: options.pendingMessage,
        });
    });
}
