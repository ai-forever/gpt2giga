import { bindPlaygroundPage } from "./playground/bindings.js";
import { buildRequestFromPreset } from "./playground/serializers.js";
import { DEFAULT_PLAYGROUND_PRESET, PLAYGROUND_PRESETS, } from "./playground/state.js";
import { renderPlaygroundHeroActions, renderPlaygroundPage, resolvePlaygroundElements, } from "./playground/view.js";
export async function renderPlayground(app, token) {
    const setup = await app.api.json("/admin/api/setup");
    if (!app.isCurrentRender(token)) {
        return;
    }
    const initialPreset = resolveInitialPlaygroundPreset(window.location);
    const initialRequest = buildRequestFromPreset(initialPreset);
    app.setHeroActions(renderPlaygroundHeroActions());
    app.setContent(renderPlaygroundPage(setup, initialPreset, initialRequest));
    const elements = resolvePlaygroundElements(app.pageContent);
    if (!elements) {
        return;
    }
    bindPlaygroundPage({
        app,
        elements,
        setup,
        token,
    });
}
function resolveInitialPlaygroundPreset(location) {
    const presetId = new URLSearchParams(location.search).get("preset")?.trim();
    if (!presetId) {
        return DEFAULT_PLAYGROUND_PRESET;
    }
    return PLAYGROUND_PRESETS.find((preset) => preset.id === presetId) ?? DEFAULT_PLAYGROUND_PRESET;
}
