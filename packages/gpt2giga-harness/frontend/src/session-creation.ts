export interface ConfiguredSessionDefaults {
  apiMode: string;
  harnessId: string;
  mode: string;
  model: string;
}

export type SessionCreationIntent =
  | { kind: "backend-defaults" }
  | { config: ConfiguredSessionDefaults; kind: "configured" };

export function sessionCreationPayload(
  intent: SessionCreationIntent,
): Readonly<Record<string, string | null>> {
  if (intent.kind === "backend-defaults") {
    return { workspace: "." };
  }
  return {
    api_mode: intent.config.apiMode,
    harness_id: intent.config.harnessId,
    mode: intent.config.mode,
    model: intent.config.model || null,
    workspace: ".",
  };
}
