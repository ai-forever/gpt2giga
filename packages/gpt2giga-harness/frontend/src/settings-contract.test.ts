import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

describe("backend-owned Settings contract", () => {
  const source = readFileSync(
    fileURLToPath(new URL("./surfaces/settings.tsx", import.meta.url)),
    "utf8",
  );

  it("renders all accepted categories with Appearance as the local boundary", () => {
    for (const category of [
      "appearance",
      "runtime",
      "provider",
      "routesModels",
      "harnessDefaults",
      "workspacePermissions",
      "mcp",
      "diagnostics",
    ]) {
      expect(source).toContain(`"${category}"`);
    }
    expect(source).toContain('<Boundary source="browser" effect="live" />');
    expect(source).toContain('patchCockpit<SettingsSaveResponse>("/api/settings/defaults"');
    expect(source).toContain("default_title_model");
    expect(source).toContain("execution_transport");
    expect(source).toContain('message(locale, "chatModel")');
    expect(source).toContain('message(locale, "titleModel")');
    expect(source).toContain('mutateCockpit<ProviderMutationResponse>("/api/providers"');
    expect(source).toContain('/test`');
    expect(source).toContain('/discover`');
    expect(source).toContain("fork_or_new_session_required");
    expect(source).toContain("providerFieldErrors(saveProvider.error)");
  });

  it("never creates browser fields for credentials, tokens, or certificates", () => {
    expect(source).not.toMatch(/type=["']password["']/u);
    expect(source).not.toMatch(/name=["'](?:api_key|token|certificate)["']/u);
    expect(source).not.toMatch(/type=["']file["']/u);
    expect(source).not.toContain("credential_value");
    expect(source).toContain('message(locale, "backendOnly")');
    expect(source).toContain("reference_name");
  });

  it("labels new-run and restart effects instead of implying live persistence", () => {
    expect(source).toContain('effect="new_runs"');
    expect(source).toContain("data.runtime.change_effect");
    expect(source).toContain("selectedProvider.effects.managed_homes");
    expect(source).toContain('effect="fork_or_new_session_required"');
  });
});
