export interface ConfiguredSessionDefaults {
  apiMode: string;
  harnessId: string;
  mode: string;
  model: string;
  productSelection: {
    authority: "read_only" | "workspace_write";
    intent: "ask" | "review" | "change";
    kind: "coding_agent" | "direct_chat";
  };
}

export type SessionCreationIntent =
  | { kind: "backend-defaults" }
  | { config: ConfiguredSessionDefaults; kind: "configured" };

export interface WorkbenchEntrySearch {
  fromSessionAction?: true;
}

export function validateWorkbenchEntrySearch(
  search: Record<string, unknown>,
): WorkbenchEntrySearch {
  return search.fromSessionAction === true || search.fromSessionAction === "true"
    ? { fromSessionAction: true }
    : {};
}

export function shouldAutomaticallyCreateSession(
  sessionId: string | undefined,
  search: WorkbenchEntrySearch,
): boolean {
  return sessionId === undefined && search.fromSessionAction !== true;
}

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
    authority: intent.config.productSelection.authority,
    task_intent: intent.config.productSelection.intent,
    workbench_kind: intent.config.productSelection.kind,
    workspace: ".",
  };
}
