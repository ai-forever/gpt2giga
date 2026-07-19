import type {
  IntegrationFlowInventory,
  IntegrationFlowSummary,
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
  source: "catalog" | "configured_mcp" | "installed_package";
  catalogId: string | null;
  targetIds: string[];
  connectedTargetIds: string[];
  connected: boolean;
  status: string;
  flow: IntegrationFlowSummary | null;
  mcp: McpProjection | null;
}

export function buildPluginLibrary(
  inventory: IntegrationFlowInventory,
  mcpServers: McpProjection[],
): PluginLibraryItem[] {
  const latestFlows = latestFlowsByPackageTarget(inventory.flows);
  const catalogPackages = new Set(inventory.catalog.map((item) => item.package_id));
  const items: PluginLibraryItem[] = inventory.catalog.map((entry) => {
    const flows = entry.target_ids
      .map((targetId) => latestFlows.get(flowKey(entry.package_id, targetId)))
      .filter((flow): flow is IntegrationFlowSummary => flow !== undefined);
    const connectedFlows = flows.filter((flow) => flow.status === "verified");
    const latestFlow = newestFlow(flows);
    return {
      id: `catalog:${entry.catalog_id}`,
      category: categoryFor(entry.component_types, entry.target_ids),
      packageId: entry.package_id,
      title: titleForPackage(entry.package_id),
      version: entry.version,
      source: "catalog" as const,
      catalogId: entry.catalog_id,
      targetIds: [...entry.target_ids].sort(),
      connectedTargetIds: connectedFlows.map((flow) => flow.target_id).sort(),
      connected: connectedFlows.length > 0,
      status: latestFlow?.status ?? "available",
      flow: latestFlow ?? null,
      mcp: null,
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
    const connectedFlows = flows.filter((flow) => flow.status === "verified");
    const targetIds = flows.map((flow) => flow.target_id).sort();
    items.push({
      id: `package:${packageId}`,
      category: categoryFor([], targetIds),
      packageId,
      title: titleForPackage(packageId),
      version: latestFlow?.package_version ?? null,
      source: "installed_package",
      catalogId: null,
      targetIds,
      connectedTargetIds: connectedFlows.map((flow) => flow.target_id).sort(),
      connected: connectedFlows.length > 0,
      status: latestFlow?.status ?? "available",
      flow: latestFlow ?? null,
      mcp: null,
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
      targetIds: [],
      connectedTargetIds: mcp.enabled ? ["harness-mcp"] : [],
      connected: mcp.enabled,
      status: mcp.status,
      flow: null,
      mcp,
    });
  }

  return items.sort((left, right) => {
    if (left.connected !== right.connected) return left.connected ? -1 : 1;
    return left.title.localeCompare(right.title);
  });
}

export function filterPluginLibrary(
  items: PluginLibraryItem[],
  category: PluginCategory,
  query: string,
  connectedOnly: boolean,
): PluginLibraryItem[] {
  const normalizedQuery = query.trim().toLocaleLowerCase();
  return items.filter((item) => {
    if (category !== "all" && item.category !== category) return false;
    if (connectedOnly && !item.connected) return false;
    if (!normalizedQuery) return true;
    return `${item.title} ${item.packageId} ${item.targetIds.join(" ")}`
      .toLocaleLowerCase()
      .includes(normalizedQuery);
  });
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
