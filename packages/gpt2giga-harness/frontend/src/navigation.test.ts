import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { primarySurfaces, surfaceForPath } from "./navigation";
import { validateOperationalSearch } from "./operational-navigation";

describe("Cockpit V2 route contract", () => {
  it("keeps the accepted five-surface order", () => {
    expect(primarySurfaces.map((surface) => surface.label)).toEqual([
      "Workbench",
      "Runs",
      "Automation",
      "Evaluation",
      "Plugins",
    ]);
  });

  it("maps exact and deep links without claiming unknown routes", () => {
    expect(surfaceForPath("/cockpit-v2/work/session_123")).toBe("work");
    expect(surfaceForPath("/cockpit-v2/runs/run_123/")).toBe("runs");
    expect(surfaceForPath("/cockpit-v2/automation/workflows")).toBe("automation");
    expect(surfaceForPath("/cockpit-v2/evaluation/baselines")).toBe("evaluation");
    expect(surfaceForPath("/cockpit-v2/plugins/skills")).toBe("integrations");
    expect(surfaceForPath("/cockpit-v2/integrations/doctor")).toBe("integrations");
    expect(surfaceForPath("/cockpit-v2/settings")).toBe("settings");
    expect(surfaceForPath("/api/runs/run_123")).toBeNull();
    expect(surfaceForPath("/cockpit-v2/assets/main.js")).toBeNull();
  });

  it("validates bounded typed row selection state", () => {
    expect(validateOperationalSearch({ selected: "route/name" })).toEqual({
      selected: "route/name",
    });
    expect(validateOperationalSearch({ selected: "" })).toEqual({});
    expect(validateOperationalSearch({ selected: ["route"] })).toEqual({});
    expect(validateOperationalSearch({ unrelated: "ignored" })).toEqual({});
  });

  it("keeps operational selection inside the router document", () => {
    const rowLinkSource = readFileSync(
      fileURLToPath(
        new URL("./components/OperationalSurface.tsx", import.meta.url),
      ),
      "utf8",
    );
    const surfaces = ["automation", "evaluation"].map((surface) =>
      readFileSync(
        fileURLToPath(new URL(`./surfaces/${surface}.tsx`, import.meta.url)),
        "utf8",
      ),
    );

    expect(rowLinkSource).toContain("<Link");
    expect(rowLinkSource).toContain("search={{ selected: selectedId }}");
    expect(rowLinkSource).not.toContain("beforeunload");
    for (const source of surfaces) {
      expect(source).toContain("<OperationalRowLink");
      expect(source).not.toMatch(/<a[^>]+className=.*operations-row/);
      expect(source).not.toContain("beforeunload");
      expect(source).not.toMatch(/href=\{?`?\/cockpit-v2\//);
    }
    const plugins = readFileSync(
      fileURLToPath(new URL("./surfaces/integrations.tsx", import.meta.url)),
      "utf8",
    );
    expect(plugins).toContain("<Link");
    expect(plugins).toContain("search={{ selected: item.id }}");
    expect(plugins).not.toContain("beforeunload");
  });

  it("resets plugin connection state when the selected item changes", () => {
    const plugins = readFileSync(
      fileURLToPath(new URL("./surfaces/integrations.tsx", import.meta.url)),
      "utf8",
    );

    expect(plugins).toContain("key={selectedItem.id}");
  });

  it("keeps workspace utilities in the rail without a static connection banner", () => {
    const shellSource = readFileSync(
      fileURLToPath(new URL("./AppShell.tsx", import.meta.url)),
      "utf8",
    );

    expect(shellSource).toContain('className="rail-utility-actions"');
    expect(shellSource).toContain("<ApprovalIcon />");
    expect(shellSource).toContain("<AttentionIcon />");
    expect(shellSource).toContain("<SettingsIcon />");
    expect(shellSource).not.toContain('className="cockpit-header"');
    expect(shellSource).not.toContain('message(preferences.locale, "connected")');
  });

  it("labels intentional full-document authoring transitions as legacy", () => {
    for (const surface of ["automation", "evaluation"]) {
      const source = readFileSync(
        fileURLToPath(new URL(`./surfaces/${surface}.tsx`, import.meta.url)),
        "utf8",
      );
      expect(source).toContain('data-legacy-transition="true"');
    }
  });
});
