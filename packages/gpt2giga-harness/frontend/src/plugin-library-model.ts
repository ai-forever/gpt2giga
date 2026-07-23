import type {
  IntegrationGroupSummary,
  IntegrationFlowInventory,
  IntegrationFlowSummary,
  IntegrationLifecycleInstallation,
  IntegrationSearchResponse,
} from "./remaining-request-graph";
import type { McpProjection } from "./surface-projections";

export type PluginCategory = "all" | "mcp" | "plugins" | "skills";
export type PluginItemCategory = Exclude<PluginCategory, "all">;

export interface PluginLibraryItem {
  id: string;
  category: PluginItemCategory;
  packageId: string;
  title: string;
  version: string | null;
  source: "catalog" | "configured_mcp" | "installed_package" | "root" | "remote";
  catalogId: string | null;
  catalogSourceType: string | null;
  targetIds: string[];
  connectedTargetIds: string[];
  connected: boolean;
  status: string;
  flow: IntegrationFlowSummary | null;
  group: IntegrationGroupSummary | null;
  lifecycle: IntegrationLifecycleInstallation | null;
  mcp: McpProjection | null;
  description: string | null;
  previewId: string | null;
  artifactUrl: string | null;
  detailUrl: string | null;
  sourceId: string | null;
  popularity: number | null;
}

export function buildPluginLibrary(
  inventory: IntegrationFlowInventory,
  mcpServers: McpProjection[],
): PluginLibraryItem[] {
  const latestFlows = latestFlowsByPackageTarget(inventory.flows);
  const latestGroups = latestGroupsByPackage(inventory.groups);
  const lifecycleByFlow = new Map(
    (inventory.installations ?? []).map((item) => [item.flow_id, item]),
  );
  const catalogPackages = new Set(inventory.catalog.map((item) => item.package_id));
  const items: PluginLibraryItem[] = inventory.catalog.map((entry) => {
    const flows = entry.target_ids
      .map((targetId) => latestFlows.get(flowKey(entry.package_id, targetId)))
      .filter((flow): flow is IntegrationFlowSummary => flow !== undefined);
    const connectedFlows = flows.filter(
      (flow) => lifecycleByFlow.get(flow.id)?.enabled ?? flow.status === "verified",
    );
    const latestFlow = newestFlow(flows);
    const latestLifecycle = latestFlow ? lifecycleByFlow.get(latestFlow.id) ?? null : null;
    const latestGroup = latestGroups.get(entry.package_id) ?? null;
    const groupedConnected = latestGroup?.status === "verified"
      && latestGroup.children.every(
        (child) => lifecycleByFlow.get(child.flow_id)?.enabled ?? child.status === "verified",
      );
    return {
      id: `catalog:${entry.catalog_id}`,
      category: categoryFor(entry.component_types, entry.target_ids),
      packageId: entry.package_id,
      title: titleForPackage(entry.package_id),
      version: entry.version,
      source: "catalog" as const,
      catalogId: entry.catalog_id,
      catalogSourceType: entry.source_type,
      targetIds: [...entry.target_ids].sort(),
      connectedTargetIds: connectedFlows.map((flow) => flow.target_id).sort(),
      connected: connectedFlows.length > 0 || groupedConnected,
      status: latestLifecycle?.state ?? latestGroup?.status ?? latestFlow?.status ?? "available",
      flow: latestFlow ?? null,
      group: latestGroup,
      lifecycle: latestLifecycle,
      mcp: null,
      description: entry.discovery?.name ?? null,
      previewId: entry.component_types.includes("skill") && entry.version !== "discovery"
        ? `catalog:${entry.catalog_id}`
        : null,
      artifactUrl: entry.discovery?.artifact_url ?? null,
      detailUrl: entry.discovery?.detail_url ?? null,
      sourceId: entry.discovery ? entry.source_type : null,
      popularity: entry.discovery?.popularity ?? null,
    };
  });

  const uncataloguedFlows = new Map<string, IntegrationFlowSummary[]>();
  for (const flow of latestFlows.values()) {
    if (catalogPackages.has(flow.package_id)) continue;
    const flows = uncataloguedFlows.get(flow.package_id) ?? [];
    flows.push(flow);
    uncataloguedFlows.set(flow.package_id, flows);
  }
  for (const [packageId, flows] of uncataloguedFlows) {
    const latestFlow = newestFlow(flows);
    const connectedFlows = flows.filter(
      (flow) => lifecycleByFlow.get(flow.id)?.enabled ?? flow.status === "verified",
    );
    const targetIds = flows.map((flow) => flow.target_id).sort();
    const latestLifecycle = latestFlow ? lifecycleByFlow.get(latestFlow.id) ?? null : null;
    items.push({
      id: `package:${packageId}`,
      category: categoryFor([], targetIds),
      packageId,
      title: titleForPackage(packageId),
      version: latestFlow?.package_version ?? null,
      source: "installed_package",
      catalogId: null,
      catalogSourceType: null,
      targetIds,
      connectedTargetIds: connectedFlows.map((flow) => flow.target_id).sort(),
      connected: connectedFlows.length > 0,
      status: latestLifecycle?.state ?? latestFlow?.status ?? "available",
      flow: latestFlow ?? null,
      group: latestGroups.get(packageId) ?? null,
      lifecycle: latestLifecycle,
      mcp: null,
      description: null,
      previewId: null,
      artifactUrl: null,
      detailUrl: null,
      sourceId: null,
      popularity: null,
    });
  }

  for (const mcp of mcpServers) {
    items.push({
      id: `mcp:${mcp.id}`,
      category: "mcp",
      packageId: mcp.id,
      title: mcp.title,
      version: null,
      source: "configured_mcp",
      catalogId: null,
      catalogSourceType: null,
      targetIds: [],
      connectedTargetIds: mcp.enabled ? ["harness-mcp"] : [],
      connected: mcp.enabled,
      status: mcp.status,
      flow: null,
      group: null,
      lifecycle: null,
      mcp,
      description: null,
      previewId: null,
      artifactUrl: null,
      detailUrl: null,
      sourceId: null,
      popularity: null,
    });
  }

  for (const skill of inventory.root_skills ?? []) {
    items.push({
      id: skill.id,
      category: "skills",
      packageId: skill.name,
      title: skill.name,
      version: null,
      source: "root",
      catalogId: null,
      catalogSourceType: "root",
      targetIds: [...skill.target_ids].sort(),
      connectedTargetIds: [...skill.target_ids].sort(),
      connected: true,
      status: "verified",
      flow: null,
      group: null,
      lifecycle: null,
      mcp: null,
      description: skill.description,
      previewId: skill.preview_id,
      artifactUrl: null,
      detailUrl: null,
      sourceId: skill.origin,
      popularity: null,
    });
  }

  return items.sort((left, right) => {
    if (left.connected !== right.connected) return left.connected ? -1 : 1;
    return left.title.localeCompare(right.title);
  });
}

export function buildRemotePluginLibrary(search: IntegrationSearchResponse | undefined): PluginLibraryItem[] {
  if (!search) return [];
  return search.items.map((item) => ({
    id: item.id,
    category: item.component === "skill" ? "skills" : "mcp",
    packageId: item.upstream_id,
    title: item.title,
    version: null,
    source: "remote",
    catalogId: null,
    catalogSourceType: item.source_id,
    targetIds: item.component === "skill"
      ? ["codex-skill", "claude-skill", "gemini-skill"]
      : ["codex-mcp", "claude-mcp", "gemini-mcp", "harness-managed-mcp"],
    connectedTargetIds: [],
    connected: false,
    status: "available",
    flow: null,
    group: null,
    lifecycle: null,
    mcp: null,
    description: item.upstream_audit,
    previewId: null,
    artifactUrl: item.artifact_url,
    detailUrl: item.detail_url,
    sourceId: item.source_id,
    popularity: item.popularity,
  }));
}

export function filterPluginLibrary(
  items: PluginLibraryItem[],
  category: PluginCategory,
  query: string,
  connectedOnly: boolean,
  sourceFilter: "all" | "built_in" | "external" = "all",
  harnessFilter: "all" | "codex" | "claude" | "gemini" | "harness" = "all",
): PluginLibraryItem[] {
  const normalizedQuery = query.trim().toLocaleLowerCase();
  return items.filter((item) => {
    if (category !== "all" && item.category !== category) return false;
    if (connectedOnly && !item.connected) return false;
    if (harnessFilter !== "all" && !item.targetIds.some((target) => (
      harnessFilter === "harness" ? target.startsWith("harness-") : target.startsWith(`${harnessFilter}-`)
    ))) return false;
    if (sourceFilter === "built_in" && item.catalogSourceType !== "local_private") return false;
    if (sourceFilter === "external" && (
      item.category === "plugins"
      || item.catalogSourceType === null
      || item.catalogSourceType === "local_private"
    )) return false;
    if (!normalizedQuery) return true;
    return `${item.title} ${item.packageId} ${item.description ?? ""} ${item.targetIds.join(" ")}`
      .toLocaleLowerCase()
      .includes(normalizedQuery);
  });
}

function latestGroupsByPackage(groups: IntegrationGroupSummary[]) {
  const result = new Map<string, IntegrationGroupSummary>();
  for (const group of groups) {
    const current = result.get(group.package_id);
    if (current === undefined || group.updated_at > current.updated_at) {
      result.set(group.package_id, group);
    }
  }
  return result;
}

function latestFlowsByPackageTarget(flows: IntegrationFlowSummary[]) {
  const result = new Map<string, IntegrationFlowSummary>();
  for (const flow of flows) {
    const key = flowKey(flow.package_id, flow.target_id);
    const current = result.get(key);
    if (current === undefined || flowTimestamp(flow) > flowTimestamp(current)) {
      result.set(key, flow);
    }
  }
  return result;
}

function newestFlow(flows: IntegrationFlowSummary[]) {
  return flows.reduce<IntegrationFlowSummary | undefined>(
    (latest, flow) => latest === undefined || flowTimestamp(flow) > flowTimestamp(latest) ? flow : latest,
    undefined,
  );
}

function flowTimestamp(flow: IntegrationFlowSummary) {
  return flow.events.at(-1)?.occurred_at ?? "";
}

function flowKey(packageId: string, targetId: string) {
  return `${packageId}\u0000${targetId}`;
}

function categoryFor(componentTypes: string[], targetIds: string[]): PluginItemCategory {
  const hints = [...componentTypes, ...targetIds].join(" ").toLowerCase();
  if (hints.includes("skill")) return "skills";
  if (hints.includes("mcp")) return "mcp";
  return "plugins";
}

function titleForPackage(packageId: string) {
  const knownTitles: Record<string, string> = {
    "gpt2giga.builtin.find-skills": "Find Skills",
    "gpt2giga.builtin.skill-creator": "Skill Creator",
    "gpt2giga.builtin.skill-installer": "Skill Installer",
  };
  const known = knownTitles[packageId];
  if (known) return known;
  return packageId
    .split(/[./_-]+/)
    .filter(Boolean)
    .slice(-3)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}
