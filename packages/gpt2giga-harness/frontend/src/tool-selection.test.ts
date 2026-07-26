import { describe, expect, it } from "vitest";

import type { IntegrationFlowInventory } from "./remaining-request-graph";
import type { SkillMention } from "./skill-mentions";
import {
  admittedBuiltinToolSelection,
  composerToolCatalog,
} from "./tool-selection";

const mentions: SkillMention[] = [
  {
    id: "skill-one",
    label: "Review helper",
    mention: "@review-helper",
    nativeName: "review-helper",
    source: "Codex",
    targetIds: ["codex-root"],
  },
  {
    id: "plugin-one",
    label: "Issue plugin",
    mention: "@issue-plugin",
    nativeName: "issue-plugin",
    source: "Shared",
    targetIds: ["codex-root"],
  },
];

const inventory = {
  catalog: [
    {
      catalog_id: "catalog-one",
      component_types: ["mcp"],
      discovery: {
        artifact_url: null,
        canonical_origin: "local",
        component: "mcp",
        content_hash: "sha256:fixture",
        curated: true,
        detail_url: null,
        discovery_location: "fixture",
        immutable_ref: "fixture-ref",
        name: "Issue MCP",
        observed_at: "2026-07-24T00:00:00Z",
        popularity: null,
        relative_path: null,
        repository_url: null,
        upstream_id: "issue-mcp",
      },
      package_id: "issue-mcp",
      scopes: ["user"],
      source_type: "local",
      target_ids: ["codex-root"],
      trust_decision: "reviewed",
      version: "1",
    },
  ],
  capability_matrix: [],
  content_free: true,
  flows: [],
  groups: [],
  installations: [],
  operations: [],
  root_plugins: [
    {
      bundled_skills: ["issue-plugin"],
      connected: true,
      default_prompts: [],
      description: "Issue workflow",
      id: "plugin-one",
      invocation: "@issue-plugin",
      name: "issue-plugin",
      origin: "shared",
      repository_url: null,
      scope: "system",
      source_label: "Shared",
      target_ids: ["codex-root"],
      title: "Issue plugin",
      version: "1",
    },
  ],
  root_skills: [],
  sources: [],
  targets: [],
} satisfies IntegrationFlowInventory;

describe("composer tool selection", () => {
  it("separates provider schemas and exposes unavailable reasons", () => {
    const groups = composerToolCatalog({
      apiMode: "v2",
      builtinTools: ["web_search"],
      harnessId: "codex-cli",
      inventory,
      kind: "coding_agent",
      query: "",
      selectedSkillIds: new Set(["skill-one"]),
      skillMentions: mentions,
      supportedBuiltinTools: [],
    });

    expect(groups.map((group) => group.category)).toEqual([
      "gigachat",
      "agent",
      "mcp",
      "skill",
      "plugin",
    ]);
    expect(groups[0]?.options[0]).toMatchObject({
      category: "gigachat",
      reason: "GigaChat built-ins are available only in Direct Chat.",
      selectable: false,
    });
    expect(groups[1]?.options[0]).toMatchObject({
      category: "agent",
      selected: true,
    });
    expect(groups[2]?.options[0]).toMatchObject({
      category: "mcp",
      label: "Issue MCP",
      selectable: false,
    });
    expect(groups[3]?.options[0]).toMatchObject({
      category: "skill",
      selected: true,
    });
    expect(groups[4]?.options[0]).toMatchObject({
      category: "plugin",
      label: "Issue plugin",
    });
  });

  it("submits only unique tools admitted by the active GigaChat schema", () => {
    expect(
      admittedBuiltinToolSelection(
        ["web_search", "unknown", "web_search"],
        ["web_search", "code_interpreter"],
        "v2",
        "direct_chat",
      ),
    ).toEqual(["web_search"]);
    expect(
      admittedBuiltinToolSelection(
        ["web_search"],
        ["web_search"],
        "v1",
        "direct_chat",
      ),
    ).toEqual([]);
    expect(
      admittedBuiltinToolSelection(
        ["web_search"],
        ["web_search"],
        "v2",
        "coding_agent",
      ),
    ).toEqual([]);
  });

  it("searches labels, details, and unavailable reasons", () => {
    const groups = composerToolCatalog({
      apiMode: "v2",
      builtinTools: [],
      harnessId: "codex-cli",
      inventory,
      kind: "coding_agent",
      query: "integration snapshot",
      selectedSkillIds: new Set(),
      skillMentions: mentions,
      supportedBuiltinTools: [],
    });

    expect(groups).toHaveLength(1);
    expect(groups[0]?.category).toBe("mcp");
    expect(groups[0]?.options[0]?.label).toBe("Issue MCP");
  });
});
