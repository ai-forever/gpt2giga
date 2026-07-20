export const cockpitBasePath = "/cockpit-v2" as const;

export const primarySurfaces = [
  { id: "work", label: "Workbench", messageKey: "workbench", path: "/cockpit-v2/work" },
  { id: "runs", label: "Runs", messageKey: "runs", path: "/cockpit-v2/runs" },
  { id: "automation", label: "Automation", messageKey: "automationNav", path: "/cockpit-v2/automation" },
  { id: "evaluation", label: "Evaluation", messageKey: "evaluation", path: "/cockpit-v2/evaluation" },
  { id: "integrations", label: "Plugins", messageKey: "plugins", path: "/cockpit-v2/plugins" },
] as const;

export type SurfaceId = (typeof primarySurfaces)[number]["id"];

export function surfaceForPath(pathname: string): SurfaceId | "settings" | null {
  const normalized = pathname.replace(/\/+$/, "") || "/";
  if (normalized === `${cockpitBasePath}/settings`) {
    return "settings";
  }
  const match = primarySurfaces.find(
    (surface) =>
      normalized === surface.path || normalized.startsWith(`${surface.path}/`),
  );
  if (normalized === `${cockpitBasePath}/integrations` || normalized.startsWith(`${cockpitBasePath}/integrations/`)) {
    return "integrations";
  }
  return match?.id ?? null;
}
