import { describePersistOutcome, withBusyState, } from "../forms.js";
import { toErrorMessage } from "../utils.js";
export function getSubmitterButton(event, form) {
    const submitter = event.submitter;
    return submitter instanceof HTMLButtonElement
        ? submitter
        : form.querySelector('button[type="submit"]');
}
export async function persistControlPlaneSection(options) {
    const pendingState = {
        tone: "info",
        message: options.pendingMessage,
    };
    options.setActionState(pendingState);
    options.refreshStatus();
    try {
        await withBusyState({
            root: options.form,
            button: options.button,
            pendingLabel: options.pendingLabel ?? "Saving…",
            action: async () => {
                const response = await options.app.api.json(options.endpoint, {
                    method: "PUT",
                    json: options.payload,
                });
                const outcome = describePersistOutcome(options.outcomeLabel, response);
                options.app.queueAlert(outcome.message, outcome.tone);
                await options.app.render(options.rerenderPage);
            },
        });
    }
    catch (error) {
        const failureState = {
            tone: "danger",
            message: `${options.failurePrefix}: ${toErrorMessage(error)}`,
        };
        options.setActionState(failureState);
        options.refreshStatus();
        options.app.pushAlert(failureState.message, "danger");
    }
}
export async function testGigachatConnection(options) {
    const pendingState = {
        tone: "info",
        message: options.pendingMessage,
    };
    options.setActionState(pendingState);
    options.refreshStatus();
    try {
        await withBusyState({
            root: options.form,
            button: options.button,
            pendingLabel: "Testing…",
            action: async () => {
                const result = await options.app.api.json("/admin/api/settings/gigachat/test", {
                    method: "POST",
                    json: options.payload,
                });
                const nextState = result.ok
                    ? buildGigachatTestSuccessState(result)
                    : buildGigachatTestFailureState(result);
                options.setActionState(nextState);
                options.refreshStatus();
                options.app.pushAlert(nextState.message, nextState.tone);
            },
        });
    }
    catch (error) {
        const failureState = {
            tone: "danger",
            message: `GigaChat connection test failed: ${toErrorMessage(error)}`,
        };
        options.setActionState(failureState);
        options.refreshStatus();
        options.app.pushAlert(failureState.message, "danger");
    }
}
function buildGigachatTestSuccessState(result) {
    return {
        tone: "info",
        message: `Connection ok. Models visible: ${String(result.model_count ?? 0)}. Candidate values were tested but not persisted.`,
    };
}
function buildGigachatTestFailureState(result) {
    return {
        tone: "danger",
        message: `Connection failed: ${String(result.error_type ?? "Error")}: ${String(result.error ?? "unknown error")}. Persisted values remain unchanged.`,
    };
}
