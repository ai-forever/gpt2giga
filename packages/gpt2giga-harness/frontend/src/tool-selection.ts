import type { IntegrationFlowInventory } from "./remaining-request-graph";
import type { SkillMention } from "./skill-mentions";
import type { WorkbenchKind } from "./workbench-execution";

export type ComposerToolCategory =
  | "agent"
  | "gigachat"
  | "mcp"
  | "plugin"
  | "skill";

export interface ComposerToolOption {
  category: ComposerToolCategory;
  detail: string;
  id: string;
  label: string;
  reason: string | null;
  selectable: boolean;
  selected: boolean;
  value: string | null;
}

export interface ComposerToolGroup {
  category: ComposerToolCategory;
  options: ComposerToolOption[];
}

interface ComposerToolCatalogInput {
  apiMode: string;
  builtinTools: readonly string[];
  harnessId: string;
  inventory: IntegrationFlowInventory | undefined;
  kind: WorkbenchKind;
  query: string;
  selectedSkillIds: ReadonlySet<string>;
  skillMentions: readonly SkillMention[];
  supportedBuiltinTools: readonly string[];
}

const gigachatBuiltinTools = [
  {
    detail: "Search current public web results through the GigaChat tool schema.",
    id: "web_search",
    label: "Web search",
  },
  {
    detail: "Run bounded calculations and code through the GigaChat tool schema.",
    id: "code_interpreter",
    label: "Code interpreter",
  },
  {
    detail: "Generate an image through the GigaChat tool schema.",
    id: "image_generate",
    label: "Image generation",
  },
  {
    detail: "Generate a 3D artifact through the GigaChat tool schema.",
    id: "model_3d_generate",
    label: "3D generation",
  },
  {
    detail: "Extract bounded content from a supplied URL.",
    id: "url_content_extraction",
    label: "URL content",
  },
] as const;

export function composerToolCatalog(
  input: ComposerToolCatalogInput,
): ComposerToolGroup[] {
  const normalizedQuery = input.query.trim().toLocaleLowerCase();
  const supportedBuiltinTools = new Set(input.supportedBuiltinTools);
  const selectedBuiltinTools = new Set(input.builtinTools);
  const pluginIds = new Set(
    (input.inventory?.root_plugins ?? []).map((plugin) => plugin.id),
  );
  const groups: ComposerToolGroup[] = [
    {
      category: "gigachat",
      options: gigachatBuiltinTools.map((tool) => {
        const reason = builtinToolReason(
          tool.id,
          input.apiMode,
          input.kind,
          supportedBuiltinTools,
        );
        return {
          category: "gigachat",
          detail: tool.detail,
          id: `gigachat:${tool.id}`,
          label: tool.label,
          reason,
          selectable: reason === null,
          selected: selectedBuiltinTools.has(tool.id),
          value: tool.id,
        };
      }),
    },
    {
      category: "agent",
      options: [
        {
          category: "agent",
          detail:
            "Filesystem, process, browser, and other provider-owned tools follow task intent and admitted authority.",
          id: "agent:runtime",
          label: "Agent tools",
          reason:
            input.kind === "coding_agent"
              ? "Runtime-managed; these are not sent as GigaChat built-ins."
              : "Choose Coding Agent to admit provider-owned agent tools.",
          selectable: false,
          selected: input.kind === "coding_agent",
          value: null,
        },
      ],
    },
    {
      category: "mcp",
      options: mcpOptions(input.inventory, input.harnessId),
    },
    {
      category: "skill",
      options: skillOptions(
        input.skillMentions,
        input.selectedSkillIds,
        pluginIds,
        "skill",
      ),
    },
    {
      category: "plugin",
      options: skillOptions(
        input.skillMentions,
        input.selectedSkillIds,
        pluginIds,
        "plugin",
      ),
    },
  ];
  return groups
    .map((group) => ({
      ...group,
      options: group.options
        .filter((option) => matchesQuery(option, normalizedQuery))
        .slice(0, 24),
    }))
    .filter((group) => group.options.length > 0);
}

export function admittedBuiltinToolSelection(
  selected: readonly string[],
  supported: readonly string[],
  apiMode: string,
  kind: WorkbenchKind,
): string[] {
  if (apiMode !== "v2" || kind !== "direct_chat") return [];
  const supportedSet = new Set(supported);
  return [...new Set(selected)].filter((tool) => supportedSet.has(tool));
}

function builtinToolReason(
  tool: string,
  apiMode: string,
  kind: WorkbenchKind,
  supported: ReadonlySet<string>,
): string | null {
  if (kind !== "direct_chat") {
    return "GigaChat built-ins are available only in Direct Chat.";
  }
  if (apiMode !== "v2") {
    return "GigaChat built-ins require the /v2 request schema.";
  }
  if (!supported.has(tool)) {
    return "The selected provider route does not advertise this tool.";
  }
  return null;
}

function mcpOptions(
  inventory: IntegrationFlowInventory | undefined,
  harnessId: string,
): ComposerToolOption[] {
  const targetPrefix = harnessTargetPrefix(harnessId);
  const seen = new Set<string>();
  const options: ComposerToolOption[] = [];
  for (const item of inventory?.catalog ?? []) {
    if (!item.component_types.includes("mcp")) continue;
    if (
      targetPrefix
      && !item.target_ids.some((target) => target.startsWith(targetPrefix))
    ) {
      continue;
    }
    const id = item.discovery?.upstream_id ?? item.package_id;
    if (seen.has(id)) continue;
    seen.add(id);
    options.push({
      category: "mcp",
      detail:
        item.discovery?.name
        ?? `${item.package_id} ${item.version}`.trim(),
      id: `mcp:${id}`,
      label: item.discovery?.name ?? item.package_id,
      reason:
        "Managed MCP tools are admitted from the bound integration snapshot, not from this prompt field.",
      selectable: false,
      selected: false,
      value: null,
    });
  }
  return options;
}

function skillOptions(
  mentions: readonly SkillMention[],
  selected: ReadonlySet<string>,
  pluginIds: ReadonlySet<string>,
  category: "plugin" | "skill",
): ComposerToolOption[] {
  return mentions
    .filter((mention) => pluginIds.has(mention.id) === (category === "plugin"))
    .map((mention) => ({
      category,
      detail: `${mention.mention} · ${mention.source}`,
      id: `${category}:${mention.id}`,
      label: mention.label,
      reason: null,
      selectable: true,
      selected: selected.has(mention.id),
      value: mention.id,
    }));
}

function harnessTargetPrefix(harnessId: string): string {
  if (harnessId.startsWith("codex")) return "codex-";
  if (harnessId.startsWith("claude")) return "claude-";
  if (harnessId.startsWith("gemini")) return "gemini-";
  return "";
}

function matchesQuery(
  option: ComposerToolOption,
  normalizedQuery: string,
): boolean {
  if (!normalizedQuery) return true;
  return `${option.label} ${option.detail} ${option.reason ?? ""}`
    .toLocaleLowerCase()
    .includes(normalizedQuery);
}
