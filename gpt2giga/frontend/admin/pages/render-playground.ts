import type { AdminApp } from "../app.js";
import type { SetupPayload } from "../types.js";
import { bindPlaygroundPage } from "./playground/bindings.js";
import { buildRequestFromPreset } from "./playground/serializers.js";
import {
  DEFAULT_PLAYGROUND_PRESET,
  PLAYGROUND_PRESETS,
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

  const initialRequest = buildRequestFromPreset(
    resolveInitialPlaygroundPreset(window.location),
  );

  app.setHeroActions(renderPlaygroundHeroActions());
  app.setContent(renderPlaygroundPage(setup, initialRequest));

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

function resolveInitialPlaygroundPreset(location: Location): PlaygroundPreset {
  const presetId = new URLSearchParams(location.search).get("preset")?.trim();
  if (!presetId) {
    return DEFAULT_PLAYGROUND_PRESET;
  }

  return PLAYGROUND_PRESETS.find((preset) => preset.id === presetId) ?? DEFAULT_PLAYGROUND_PRESET;
}
