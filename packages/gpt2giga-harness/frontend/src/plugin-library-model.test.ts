import { describe, expect, it } from "vitest";

import {
  buildRemotePluginLibrary,
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
    source_type: "local_private",
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
  groups: [],
  installations: [],
  capability_matrix: [],
  operations: [],
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
    expect(filterPluginLibrary(items, "all", "", false, "external")).toEqual([]);
  });

  it("uses effective lifecycle state instead of treating retained disabled files as connected", () => {
    const withLifecycle: IntegrationFlowInventory = {
      ...inventory,
      installations: [{
        flow_id: "plugin-installed",
        package_id: "acme.review-tools",
        package_version: "2.0.0",
        target_id: "codex-plugin",
        scope: "managed_home",
        state: "disabled",
        enabled: false,
        installed: true,
        revision: 2,
        catalog_id: null,
        last_operation_id: "iop-1",
        updated_at: "2026-07-19T13:00:00Z",
        content_free: true,
      }],
    };

    expect(
      buildPluginLibrary(withLifecycle, []).find(
        (item) => item.packageId === "acme.review-tools",
      ),
    ).toMatchObject({
      connected: false,
      status: "disabled",
      lifecycle: { state: "disabled", installed: true },
    });
  });

  it("projects verified and repair-required all-target groups without inventing plugin sources", () => {
    const grouped: IntegrationFlowInventory = {
      ...inventory,
      flows: [],
      groups: [{
        id: "group-1",
        plan_id: "plan-1",
        status: "verified",
        component: "skill",
        source: "catalog",
        catalog_id: "find-skills-1",
        package_id: "gpt2giga.builtin.find-skills",
        package_version: "1.0.0",
        target_mode: "all_supported",
        target_ids: ["codex-skill", "claude-skill", "gemini-skill"],
        aggregate_risk: "reviewed",
        approval_hash: "approval-1",
        children: [],
        repair_actions: [],
        rollback_available: true,
        updated_at: "2026-07-20T10:00:00Z",
      }],
    };

    const [item] = buildPluginLibrary(grouped, []);
    expect(item).toBeDefined();
    if (!item) throw new Error("grouped catalog item is missing");
    expect(item).toMatchObject({ connected: true, status: "verified" });
    expect(item.group?.target_mode).toBe("all_supported");
  });

  it("projects root skills, federated results, and filters them by harness", () => {
    const items = buildPluginLibrary({
      ...inventory,
      root_skills: [{
        id: "root:abc",
        name: "Shared review",
        description: "Installed for every native harness",
        target_ids: ["codex-skill", "claude-skill", "gemini-skill"],
        origin: "root",
        scope: "root",
        connected: true,
        preview_id: "root:abc",
      }],
    }, []);
    const remote = buildRemotePluginLibrary({
      query: "review",
      items: [{
        id: "remote:skills-sh:review",
        source_id: "skills-sh",
        upstream_id: "acme/review",
        title: "Remote review",
        component: "skill",
        artifact_url: "https://github.com/acme/review",
        detail_url: "https://skills.sh/acme/review",
        curated: false,
        popularity: 42,
        upstream_audit: null,
        canonical_origin: "https://skills.sh",
        observed_at: "2026-07-24T08:00:00Z",
        discovery_location: "skills-sh/acme/review",
        install_authorized: false,
      }],
      sources: [{ id: "skills-sh", status: "ready", error_type: null }],
      install_authorized: false,
    });

    expect(items.find((item) => item.id === "root:abc")).toMatchObject({
      connected: true,
      previewId: "root:abc",
      source: "root",
    });
    expect(filterPluginLibrary(items, "skills", "", false, "all", "claude")
      .some((item) => item.id === "root:abc")).toBe(true);
    expect(filterPluginLibrary(items, "skills", "", false, "all", "harness")
      .some((item) => item.id === "root:abc")).toBe(false);
    expect(remote[0]).toMatchObject({
      artifactUrl: "https://github.com/acme/review",
      sourceId: "skills-sh",
      popularity: 42,
      provenance: {
        canonical_source: "skills-sh",
        upstream_id: "acme/review",
        canonical_origin: "https://skills.sh",
        discovery_location: "skills-sh/acme/review",
      },
    });
  });
});
