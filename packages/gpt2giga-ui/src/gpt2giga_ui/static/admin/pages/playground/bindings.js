import { abortPlaygroundRequest, disposePlaygroundRequestState, executePlaygroundRequest, } from "./api.js";
import { applyPreset, buildRequest } from "./serializers.js";
import { createIdleRunState, createPlaygroundPageState, getPlaygroundFields, PLAYGROUND_PRESETS, } from "./state.js";
import { updatePlaygroundRequestPreview, updatePlaygroundRunPanels, } from "./view.js";
export function bindPlaygroundPage(options) {
    const { app, elements, setup, token } = options;
    const state = createPlaygroundPageState();
    const refreshAll = () => {
        const request = buildRequest(elements.form);
        updatePlaygroundRequestPreview({
            elements,
            gatewayKey: elements.gatewayKeyInput?.value.trim() ?? "",
            request,
            setup,
        });
        syncPresetButtons();
        updatePlaygroundRunPanels({ elements, state });
    };
    const resetRunState = () => {
        Object.assign(state.runState, createIdleRunState());
        state.streamEvents.length = 0;
        updatePlaygroundRunPanels({ elements, state });
    };
    const startRequest = async () => {
        const request = buildRequest(elements.form);
        const fields = getPlaygroundFields(elements.form);
        if (!fields.model.value.trim()) {
            fields.model.setCustomValidity("Model is required.");
            fields.model.reportValidity();
            return;
        }
        if (!fields.user_prompt.value.trim()) {
            fields.user_prompt.setCustomValidity("User prompt is required.");
            fields.user_prompt.reportValidity();
            return;
        }
        await executePlaygroundRequest({
            gatewayKey: elements.gatewayKeyInput?.value.trim() ?? "",
            isCurrentRender: (renderToken) => app.isCurrentRender(renderToken),
            onUpdate: () => updatePlaygroundRunPanels({ elements, state }),
            request,
            state,
            token,
        });
    };
    const syncPresetButtons = () => {
        const fields = getPlaygroundFields(elements.form);
        elements.presetButtons.forEach((button) => {
            const preset = PLAYGROUND_PRESETS.find((item) => item.id === button.dataset.preset);
            const selected = preset !== undefined &&
                preset.surface === fields.surface.value &&
                preset.model === fields.model.value.trim() &&
                preset.stream === (fields.stream.value === "true") &&
                preset.systemPrompt === fields.system_prompt.value &&
                preset.userPrompt === fields.user_prompt.value;
            button.dataset.active = selected ? "true" : "false";
            button.setAttribute("aria-pressed", selected ? "true" : "false");
            button.classList.toggle("button--secondary", !selected);
        });
    };
    elements.form.addEventListener("submit", async (event) => {
        event.preventDefault();
        await startRequest();
    });
    elements.form.addEventListener("input", () => {
        const fields = getPlaygroundFields(elements.form);
        fields.model.setCustomValidity("");
        fields.user_prompt.setCustomValidity("");
        refreshAll();
    });
    elements.form.addEventListener("change", refreshAll);
    elements.gatewayKeyInput?.addEventListener("input", refreshAll);
    elements.presetButtons.forEach((button) => {
        button.addEventListener("click", () => {
            const preset = PLAYGROUND_PRESETS.find((item) => item.id === button.dataset.preset);
            if (!preset) {
                return;
            }
            applyPreset(elements.form, preset);
            refreshAll();
        });
    });
    elements.stopButton?.addEventListener("click", () => abortPlaygroundRequest(state));
    elements.resetButton?.addEventListener("click", resetRunState);
    app.registerCleanup(() => {
        disposePlaygroundRequestState(state);
        elements.gatewayKeyInput?.removeEventListener("input", refreshAll);
    });
    refreshAll();
}
