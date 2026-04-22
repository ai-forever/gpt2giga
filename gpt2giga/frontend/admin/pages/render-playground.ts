import type { AdminApp } from "../app.js";
import type { SetupPayload } from "../types.js";
import { bindPlaygroundPage } from "./playground/bindings.js";
import { buildRequestFromPreset } from "./playground/serializers.js";
import {
  DEFAULT_PLAYGROUND_PRESET_ID,
  buildPlaygroundPresets,
  type PlaygroundPreset,
} from "./playground/state.js";
import {
  renderPlaygroundHeroActions,
  renderPlaygroundPage,
  resolvePlaygroundElements,
} from "./playground/view.js";

export async function renderPlayground(app: AdminApp, token: number): Promise<void> {
  const setup = await app.api.json<SetupPayload>("/admin/api/setup");
  if (!app.isCurrentRender(token)) {
    return;
  }

  const presets = buildPlaygroundPresets(app.runtime?.gigachat_model);
  const initialPreset = resolveInitialPlaygroundPreset(window.location, presets);
  const initialRequest = buildRequestFromPreset(initialPreset);

  app.setHeroActions(renderPlaygroundHeroActions());
  app.setContent(renderPlaygroundPage(setup, presets, initialPreset, initialRequest));

  const elements = resolvePlaygroundElements(app.pageContent);
  if (!elements) {
    return;
  }

  bindPlaygroundPage({
    app,
    elements,
    presets,
    setup,
    token,
  });
}

function resolveInitialPlaygroundPreset(
  location: Location,
  presets: PlaygroundPreset[],
): PlaygroundPreset {
  const presetId = new URLSearchParams(location.search).get("preset")?.trim();
  if (!presetId) {
    return (
      presets.find((preset) => preset.id === DEFAULT_PLAYGROUND_PRESET_ID) ?? presets[0]!
    );
  }

  return (
    presets.find((preset) => preset.id === presetId) ??
    presets.find((preset) => preset.id === DEFAULT_PLAYGROUND_PRESET_ID) ??
    presets[0]!
  );
}
