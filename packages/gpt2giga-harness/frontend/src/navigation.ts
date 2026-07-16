export const cockpitBasePath = "/cockpit-v2" as const;

export const primarySurfaces = [
  { id: "work", label: "Workbench", messageKey: "workbench", path: "/cockpit-v2/work" },
  { id: "runs", label: "Runs", messageKey: "runs", path: "/cockpit-v2/runs" },
  { id: "automation", label: "Automation", messageKey: "automationNav", path: "/cockpit-v2/automation" },
  { id: "evaluation", label: "Evaluation", messageKey: "evaluation", path: "/cockpit-v2/evaluation" },
  { id: "integrations", label: "Integrations", messageKey: "integrations", path: "/cockpit-v2/integrations" },
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
  return match?.id ?? null;
}
