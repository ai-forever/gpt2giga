import { describe, expect, it } from "vitest";

import {
  buildPluginLibrary,
  filterPluginLibrary,
} from "./plugin-library-model";
import type { IntegrationFlowInventory } from "./remaining-request-graph";

const inventory: IntegrationFlowInventory = {
  sources: [{ id: "catalog", network_required: false }],
  targets: [
    { id: "codex-skill", component_types: ["skill"], scopes: ["managed_home"], execution_owner: "installer" },
    { id: "codex-plugin", component_types: ["plugin"], scopes: ["managed_home"], execution_owner: "installer" },
  ],
  catalog: [{
    catalog_id: "find-skills-1",
    package_id: "gpt2giga.builtin.find-skills",
    version: "1.0.0",
    component_types: ["skill"],
    target_ids: ["codex-skill"],
    scopes: ["managed_home"],
    trust_decision: "reviewed",
  }],
  flows: [
    {
      id: "older-verified",
      plan_id: "plan-1",
      status: "verified",
      package_id: "gpt2giga.builtin.find-skills",
      package_version: "1.0.0",
      target_id: "codex-skill",
      scope: "managed_home",
      verification_status: "discovered",
      rollback_available: true,
      events: [{ stage: "verify", status: "verified", occurred_at: "2026-07-19T10:00:00Z", code: null }],
    },
    {
      id: "newer-rollback",
      plan_id: "plan-1",
      status: "rolled_back",
      package_id: "gpt2giga.builtin.find-skills",
      package_version: "1.0.0",
      target_id: "codex-skill",
      scope: "managed_home",
      verification_status: "rolled_back",
      rollback_available: false,
      events: [{ stage: "rollback", status: "rolled_back", occurred_at: "2026-07-19T11:00:00Z", code: null }],
    },
    {
      id: "plugin-installed",
      plan_id: "plan-2",
      status: "verified",
      package_id: "acme.review-tools",
      package_version: "2.0.0",
      target_id: "codex-plugin",
      scope: "managed_home",
      verification_status: "discovered",
      rollback_available: true,
      events: [{ stage: "verify", status: "verified", occurred_at: "2026-07-19T12:00:00Z", code: null }],
    },
  ],
  content_free: true,
};

describe("plugin library model", () => {
  it("projects catalog, installed packages, and configured MCP without overstating rollback state", () => {
    const items = buildPluginLibrary(inventory, [{
      id: "repo-search",
      title: "Repository Search",
      transport: "stdio",
      enabled: true,
      trusted: true,
      status: "ready",
    }]);

    expect(items).toHaveLength(3);
    expect(items.find((item) => item.packageId === "gpt2giga.builtin.find-skills")).toMatchObject({
      category: "skills",
      connected: false,
      status: "rolled_back",
    });
    expect(items.find((item) => item.packageId === "acme.review-tools")).toMatchObject({
      category: "plugins",
      connected: true,
    });
    expect(items.find((item) => item.packageId === "repo-search")).toMatchObject({
      category: "mcp",
      connected: true,
    });
  });

  it("filters by category, connection state, and searchable target metadata", () => {
    const items = buildPluginLibrary(inventory, []);

    expect(filterPluginLibrary(items, "plugins", "", true).map((item) => item.packageId)).toEqual([
      "acme.review-tools",
    ]);
    expect(filterPluginLibrary(items, "all", "codex-skill", false).map((item) => item.packageId)).toEqual([
      "gpt2giga.builtin.find-skills",
    ]);
  });
});
