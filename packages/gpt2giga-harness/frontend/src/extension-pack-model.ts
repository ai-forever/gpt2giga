import type { IntegrationFlowInventory, IntegrationGroupPlan } from "./remaining-request-graph";

export function extensionPackCatalogOptions(inventory: IntegrationFlowInventory) {
  return {
    skills: inventory.catalog.filter((item) => item.component_types.includes("skill")),
    mcp: inventory.catalog.filter((item) => item.component_types.includes("mcp")),
  };
}

export function parseExtensionPackConfiguration(raw: string): Record<string, unknown> {
  const parsed: unknown = JSON.parse(raw);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("MCP configuration must be an object");
  }
  return parsed as Record<string, unknown>;
}

export function includedExtensionPackTargets(plan: IntegrationGroupPlan) {
  return (plan.compatibility ?? [])
    .filter((item) => item.included)
    .map((item) => item.target);
}
