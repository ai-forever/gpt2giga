import { describe, expect, it } from "vitest";

import { primarySurfaces, surfaceForPath } from "./navigation";

describe("Cockpit V2 route contract", () => {
  it("keeps the accepted five-surface order", () => {
    expect(primarySurfaces.map((surface) => surface.label)).toEqual([
      "Workbench",
      "Runs",
      "Automation",
      "Evaluation",
      "Integrations",
    ]);
  });

  it("maps exact and deep links without claiming unknown routes", () => {
    expect(surfaceForPath("/cockpit-v2/work/session_123")).toBe("work");
    expect(surfaceForPath("/cockpit-v2/runs/run_123/")).toBe("runs");
    expect(surfaceForPath("/cockpit-v2/settings")).toBe("settings");
    expect(surfaceForPath("/api/runs/run_123")).toBeNull();
    expect(surfaceForPath("/cockpit-v2/assets/main.js")).toBeNull();
  });
});
