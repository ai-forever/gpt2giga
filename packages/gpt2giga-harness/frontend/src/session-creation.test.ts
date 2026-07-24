import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import {
  sessionCreationPayload,
  shouldAutomaticallyCreateSession,
  validateWorkbenchEntrySearch,
} from "./session-creation";

describe("Workbench session creation", () => {
  const workbenchSource = readFileSync(
    fileURLToPath(new URL("./surfaces/workbench.tsx", import.meta.url)),
    "utf8",
  );

  it("leaves automatic entry defaults under backend ownership", () => {
    expect(sessionCreationPayload({ kind: "backend-defaults" })).toEqual({
      workspace: ".",
    });
  });

  it("preserves explicit New session selections", () => {
    expect(sessionCreationPayload({
      config: {
        apiMode: "v2",
        harnessId: "codex-cli",
        mode: "plan",
        model: "ConfiguredModel",
      },
      kind: "configured",
    })).toEqual({
      api_mode: "v2",
      harness_id: "codex-cli",
      mode: "plan",
      model: "ConfiguredModel",
      workspace: ".",
    });
  });

  it("opens one backend-default session and focuses its composer", () => {
    expect(workbenchSource).toContain("automaticSessionRequested.current = true");
    expect(workbenchSource).toContain('createSessionMutate({ kind: "backend-defaults" })');
    expect(workbenchSource).toContain("composerRef.current?.focus()");
  });

  it("creates automatically only on a direct empty workbench entry", () => {
    expect(shouldAutomaticallyCreateSession(undefined, {})).toBe(true);
    expect(shouldAutomaticallyCreateSession("session_123", {})).toBe(false);
    expect(shouldAutomaticallyCreateSession(undefined, { fromSessionAction: true })).toBe(false);
  });

  it("retains the bounded internal-navigation marker", () => {
    expect(validateWorkbenchEntrySearch({ fromSessionAction: true })).toEqual({
      fromSessionAction: true,
    });
    expect(validateWorkbenchEntrySearch({ fromSessionAction: "true" })).toEqual({
      fromSessionAction: true,
    });
    expect(validateWorkbenchEntrySearch({ fromSessionAction: false })).toEqual({});
    expect(validateWorkbenchEntrySearch({ unrelated: "ignored" })).toEqual({});
  });

  it("keeps row actions separate from navigation and only clears the active session", () => {
    expect(workbenchSource).toContain('className="session-row-link"');
    expect(workbenchSource).toContain('className="session-row-actions"');
    expect(workbenchSource).toContain("if (id === sessionId)");
    expect(workbenchSource).toContain("search: { fromSessionAction: true }");
  });
});
