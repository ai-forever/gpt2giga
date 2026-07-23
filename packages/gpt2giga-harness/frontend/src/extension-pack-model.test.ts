import { describe, expect, it } from "vitest";

import {
  extensionPackCatalogOptions,
  includedExtensionPackTargets,
  parseExtensionPackConfiguration,
} from "./extension-pack-model";
import type { IntegrationFlowInventory, IntegrationGroupPlan } from "./remaining-request-graph";

describe("portable extension pack model", () => {
  it("keeps reviewed Skill and MCP catalog choices separate", () => {
    const inventory = {
      catalog: [
        { catalog_id: "skill", component_types: ["skill"] },
        { catalog_id: "mcp", component_types: ["mcp"] },
        { catalog_id: "plugin", component_types: ["plugin"] },
      ],
    } as IntegrationFlowInventory;

    const options = extensionPackCatalogOptions(inventory);

    expect(options.skills.map((item) => item.catalog_id)).toEqual(["skill"]);
    expect(options.mcp.map((item) => item.catalog_id)).toEqual(["mcp"]);
  });

  it("accepts only object MCP configuration", () => {
    expect(parseExtensionPackConfiguration('{"selection":{"kind":"remote"}}')).toEqual({
      selection: { kind: "remote" },
    });
    expect(() => parseExtensionPackConfiguration("[]")).toThrow(
      "MCP configuration must be an object",
    );
  });

  it("uses the server compatibility matrix as the inclusion authority", () => {
    const plan = {
      compatibility: [
        { target: "codex", included: true },
        { target: "claude", included: false },
        { target: "harness", included: true },
      ],
    } as IntegrationGroupPlan;

    expect(includedExtensionPackTargets(plan)).toEqual(["codex", "harness"]);
  });
});
