import { describe, expect, it } from "vitest";

import type { IntegrationFlowInventory } from "./remaining-request-graph";
import {
  promptWithSkillMentions,
  skillMentionOptions,
} from "./skill-mentions";

const inventory = {
  root_skills: [{
    id: "root:review",
    name: "review",
    description: "Review a change.",
    target_ids: ["codex-skill", "claude-skill"],
    origin: "root",
    scope: "root",
    connected: true,
    preview_id: "root:review",
  }],
  root_plugins: [{
    id: "plugin:pdf",
    name: "pdf",
    title: "PDF",
    description: "Work with PDFs.",
    version: "1.0.0",
    target_ids: ["codex-plugin"],
    origin: "openai-primary-runtime",
    source_label: "OpenAI",
    scope: "system",
    connected: true,
    invocation: "@pdf",
    bundled_skills: ["pdf"],
    default_prompts: [],
    repository_url: null,
  }, {
    id: "plugin:presentations",
    name: "presentations",
    title: "Presentations",
    description: "Create presentations.",
    version: "1.0.0",
    target_ids: ["codex-plugin"],
    origin: "openai-primary-runtime",
    source_label: "OpenAI",
    scope: "system",
    connected: true,
    invocation: "@presentations",
    bundled_skills: ["Presentations"],
    default_prompts: [],
    repository_url: null,
  }],
} as unknown as IntegrationFlowInventory;

describe("Workbench skill mentions", () => {
  it("offers OpenAI bundled plugins through the @ picker for Codex", () => {
    expect(skillMentionOptions(inventory, "codex-cli", "pd")).toEqual([
      expect.objectContaining({
        label: "PDF",
        mention: "@pdf",
        nativeName: "pdf",
        source: "OpenAI",
      }),
    ]);
    expect(skillMentionOptions(inventory, "claude-code", "pdf")).toEqual([]);
  });

  it("keeps the plugin @ name while preserving its native Skill name", () => {
    expect(skillMentionOptions(inventory, "codex-cli", "present")).toEqual([
      expect.objectContaining({
        label: "Presentations",
        mention: "@presentations",
        nativeName: "Presentations",
      }),
    ]);
  });

  it("translates ChatGPT-style @ selection to the native Codex skill syntax", () => {
    const skills = skillMentionOptions(inventory, "codex-cli", "pdf");
    expect(promptWithSkillMentions("Review the attached report.", skills, "codex-cli"))
      .toBe("$pdf\n\nReview the attached report.");
  });
});
