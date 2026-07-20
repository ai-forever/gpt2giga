import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { sessionCreationPayload } from "./session-creation";

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
});
