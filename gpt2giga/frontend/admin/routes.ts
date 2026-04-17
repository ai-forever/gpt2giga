import type { PageId, RouteMeta, WorkflowId, WorkflowMeta } from "./types.js";

interface SubpageNavItem {
  description: string;
  label: string;
  page: PageId;
}

export const WORKFLOW_META: Record<WorkflowId, WorkflowMeta> = {
  start: {
    label: "Start",
    description: "Bootstrap the gateway, confirm readiness, and run the first smoke request.",
  },
  configure: {
    label: "Configure",
    description: "Persist control-plane posture, rotate keys, and tune day-2 operator settings.",
  },
  observe: {
    label: "Observe",
    description: "Start from request summaries, then hand off into log context only when needed.",
  },
  diagnose: {
    label: "Diagnose",
    description: "Inspect runtime posture, provider coverage, and advanced workbench surfaces.",
  },
};

export const WORKFLOW_ORDER: WorkflowId[] = ["start", "configure", "observe", "diagnose"];

export const PAGE_META: Record<PageId, RouteMeta> = {
  overview: {
    eyebrow: "Overview",
    title: "Gateway overview",
    subtitle: "Health, setup state, usage, and operator warnings.",
    workflow: "start",
    navDescription:
      "Summary-first posture view with the next operator action already narrowed down.",
  },
  setup: {
    eyebrow: "Setup",
    title: "Setup hub",
    subtitle: "Bootstrap progress, warnings, and the next step.",
    workflow: "start",
    navDescription:
      "Summary-first bootstrap hub with direct handoff into claim, application, GigaChat, and security steps.",
  },
  "setup-claim": {
    eyebrow: "Setup",
    title: "Claim bootstrap session",
    subtitle:
      "Record the first operator for PROD bootstrap before continuing with setup.",
    workflow: "start",
    navDescription:
      "Focused claim workflow for the first bootstrap operator session.",
  },
  "setup-application": {
    eyebrow: "Setup",
    title: "Application bootstrap posture",
    subtitle:
      "Persist runtime mode and provider posture without the rest of the setup noise.",
    workflow: "start",
    navDescription:
      "Focused application bootstrap step for runtime mode and provider posture.",
  },
  "setup-gigachat": {
    eyebrow: "Setup",
    title: "GigaChat bootstrap",
    subtitle:
      "Configure credentials, test connectivity, and stage GigaChat runtime settings.",
    workflow: "start",
    navDescription:
      "Focused GigaChat setup step with credential staging and connection testing.",
  },
  "setup-security": {
    eyebrow: "Setup",
    title: "Security bootstrap",
    subtitle:
      "Close bootstrap access and stage gateway auth without leaving the setup flow.",
    workflow: "start",
    navDescription:
      "Focused security bootstrap step for gateway auth, CORS, and global key rotation.",
  },
  settings: {
    eyebrow: "Settings",
    title: "Settings hub",
    subtitle: "Focused pages for config and revision history.",
    workflow: "configure",
    navDescription:
      "Summary-first settings hub with direct handoff into one configuration area at a time.",
  },
  "settings-application": {
    eyebrow: "Settings",
    title: "Application settings",
    subtitle:
      "Edit runtime mode, provider posture, and restart-sensitive application controls.",
    workflow: "configure",
    navDescription:
      "Focused application settings surface for runtime posture and provider routing.",
  },
  "settings-observability": {
    eyebrow: "Settings",
    title: "Observability settings",
    subtitle:
      "Manage telemetry sinks, endpoints, and observability presets on a dedicated page.",
    workflow: "configure",
    navDescription:
      "Focused observability settings surface for telemetry sink posture and presets.",
  },
  "settings-gigachat": {
    eyebrow: "Settings",
    title: "GigaChat settings",
    subtitle:
      "Persist credentials, transport settings, and connection-test candidate values.",
    workflow: "configure",
    navDescription:
      "Focused GigaChat settings surface for provider auth and connectivity checks.",
  },
  "settings-security": {
    eyebrow: "Settings",
    title: "Security settings",
    subtitle:
      "Edit gateway auth, logs access, CORS, and governance limits in one focused surface.",
    workflow: "configure",
    navDescription:
      "Focused security settings surface for gateway auth and operator guardrails.",
  },
  "settings-history": {
    eyebrow: "Settings",
    title: "Settings history",
    subtitle:
      "Review persisted revisions and rollback snapshots without sharing space with forms.",
    workflow: "configure",
    navDescription:
      "Focused revision history surface for rollback and persisted change review.",
  },
  keys: {
    eyebrow: "Keys",
    title: "API key control",
    subtitle:
      "Create, rotate, and revoke gateway keys without touching environment files.",
    workflow: "configure",
    navDescription: "Manage global and scoped gateway auth without editing env files by hand.",
  },
  logs: {
    eyebrow: "Logs",
    title: "Live log surface",
    subtitle:
      "Tail logs, stream new lines, and inspect failures without leaving the console.",
    workflow: "observe",
    navDescription: "Deep-dive into one request or failure after Traffic narrows the scope.",
  },
  playground: {
    eyebrow: "Playground",
    title: "Manual request playground",
    subtitle: "Run compatibility requests directly against this proxy.",
    workflow: "start",
    navDescription:
      "Smoke the mounted compatibility routes before exposing them to real clients.",
  },
  traffic: {
    eyebrow: "Traffic",
    title: "Traffic summary",
    subtitle: "Recent requests, errors, and usage before drill-down.",
    workflow: "observe",
    navDescription:
      "Summary-first observe hub with direct handoff into focused request, error, and usage pages.",
  },
  "traffic-requests": {
    eyebrow: "Traffic",
    title: "Request traffic",
    subtitle:
      "Focus on recent request rows, request pinning, and request-scoped handoff into Logs.",
    workflow: "observe",
    navDescription:
      "Focused request traffic page for recent request review and request-scoped log handoff.",
  },
  "traffic-errors": {
    eyebrow: "Traffic",
    title: "Error traffic",
    subtitle:
      "Focus on recent failures, error patterns, and the next diagnostic handoff without usage noise.",
    workflow: "observe",
    navDescription:
      "Focused error traffic page for failure review and escalation into raw logs only when needed.",
  },
  "traffic-usage": {
    eyebrow: "Traffic",
    title: "Usage traffic",
    subtitle:
      "Focus on provider and API-key rollups without the request and error tables competing for attention.",
    workflow: "observe",
    navDescription:
      "Focused usage traffic page for provider and key rollups with lighter handoff back to requests.",
  },
  providers: {
    eyebrow: "Providers",
    title: "Provider surfaces",
    subtitle:
      "Enabled providers, backend posture, and live capability coverage in one view.",
    workflow: "diagnose",
    navDescription:
      "Compare configured providers against mounted routes and live capability coverage.",
  },
  "files-batches": {
    eyebrow: "Files & Batches",
    title: "Files and batch workbench",
    subtitle:
      "Start from the shared workbench, then narrow into focused files or batches views as needed.",
    workflow: "diagnose",
    navDescription:
      "Shared workbench hub for stored inputs, batch lifecycles, and downstream output handoff.",
  },
  files: {
    eyebrow: "Files & Batches",
    title: "Files workbench",
    subtitle:
      "Focus on upload, stored file inventory, and file preview without the batch workflow noise.",
    workflow: "diagnose",
    navDescription:
      "Focused file inventory and preview view inside the files and batches workflow.",
  },
  batches: {
    eyebrow: "Files & Batches",
    title: "Batch jobs workbench",
    subtitle:
      "Focus on batch creation, lifecycle inspection, and output handoff without upload-first clutter.",
    workflow: "diagnose",
    navDescription:
      "Focused batch lifecycle view inside the files and batches workflow.",
  },
  system: {
    eyebrow: "System",
    title: "System posture",
    subtitle:
      "Readiness, runtime health, effective config, and diagnostics for this gateway.",
    workflow: "diagnose",
    navDescription:
      "Runtime, config, and route diagnostics when the operator story feels inconsistent.",
  },
};

export const PAGE_ORDER = Object.keys(PAGE_META) as PageId[];

const NAV_ENTRY_BY_PAGE: Partial<Record<PageId, PageId>> = {
  "setup-claim": "setup",
  "setup-application": "setup",
  "setup-gigachat": "setup",
  "setup-security": "setup",
  "settings-application": "settings",
  "settings-observability": "settings",
  "settings-gigachat": "settings",
  "settings-security": "settings",
  "settings-history": "settings",
  "traffic-requests": "traffic",
  "traffic-errors": "traffic",
  "traffic-usage": "traffic",
  files: "files-batches",
  batches: "files-batches",
};

const SETTINGS_SECTION_PAGE: Record<string, PageId> = {
  application: "settings-application",
  observability: "settings-observability",
  gigachat: "settings-gigachat",
  security: "settings-security",
  history: "settings-history",
};

const SUBPAGE_NAV: Record<string, SubpageNavItem[]> = {
  setup: [
    {
      page: "setup",
      label: "Overview",
      description: "Progress, readiness, warnings, and the next recommended step.",
    },
    {
      page: "setup-claim",
      label: "Claim",
      description: "Record the first bootstrap operator when claim is required.",
    },
    {
      page: "setup-application",
      label: "Application",
      description: "Persist runtime mode and provider posture for bootstrap.",
    },
    {
      page: "setup-gigachat",
      label: "GigaChat",
      description: "Configure credentials and test the provider connection.",
    },
    {
      page: "setup-security",
      label: "Security",
      description: "Close bootstrap access and stage gateway auth posture.",
    },
  ],
  settings: [
    {
      page: "settings",
      label: "Overview",
      description: "Summary and entrypoint cards for the main settings areas.",
    },
    {
      page: "settings-application",
      label: "Application",
      description: "Runtime mode, provider posture, and restart-sensitive controls.",
    },
    {
      page: "settings-observability",
      label: "Observability",
      description: "Telemetry sinks, endpoints, and preset staging.",
    },
    {
      page: "settings-gigachat",
      label: "GigaChat",
      description: "Credentials, transport settings, and connection testing.",
    },
    {
      page: "settings-security",
      label: "Security",
      description: "Gateway auth, logs access, CORS, and governance limits.",
    },
    {
      page: "settings-history",
      label: "History",
      description: "Recent persisted revisions and rollback actions.",
    },
  ],
  "files-batches": [
    {
      page: "files-batches",
      label: "Overview",
      description: "Shared workbench summary for uploads, jobs, and handoff state.",
    },
    {
      page: "files",
      label: "Files",
      description: "Stored file inventory, upload, and content preview.",
    },
    {
      page: "batches",
      label: "Batches",
      description: "Batch creation, lifecycle review, and output handoff.",
    },
  ],
  traffic: [
    {
      page: "traffic",
      label: "Overview",
      description: "Summary-first request, error, and usage posture before drilling deeper.",
    },
    {
      page: "traffic-requests",
      label: "Requests",
      description: "Recent request feed, request pinning, and request-scoped log handoff.",
    },
    {
      page: "traffic-errors",
      label: "Errors",
      description: "Recent failure feed, error pattern review, and raw log escalation.",
    },
    {
      page: "traffic-usage",
      label: "Usage",
      description: "Provider and API-key rollups without request-table overload.",
    },
  ],
};

export function pathForPage(page: PageId): string {
  return page === "overview" ? "/admin" : `/admin/${page}`;
}

export function isPageId(value: string): value is PageId {
  return PAGE_ORDER.includes(value as PageId);
}

export function navEntryForPage(page: PageId): PageId {
  return NAV_ENTRY_BY_PAGE[page] ?? page;
}

export function subpagesFor(page: PageId): SubpageNavItem[] {
  return SUBPAGE_NAV[navEntryForPage(page)] ?? [];
}

export function pageFromLocation(location: Location): PageId {
  const params = new URLSearchParams(location.search);
  const queryPage = params.get("tab")?.trim();
  const candidate = queryPage && isPageId(queryPage)
    ? queryPage
    : normalizePathnameToPage(location.pathname);

  if (candidate === "settings") {
    return SETTINGS_SECTION_PAGE[params.get("section")?.trim() ?? ""] ?? candidate;
  }

  return candidate;
}

export function isConsolePathname(pathname: string): boolean {
  return pathname === "/admin" || PAGE_ORDER.some((page) => pathForPage(page) === pathname);
}

export function pagesForWorkflow(workflow: WorkflowId): PageId[] {
  return PAGE_ORDER.filter((page) => PAGE_META[page].workflow === workflow);
}

function normalizePathnameToPage(pathname: string): PageId {
  const path = pathname.replace(/^\/admin\/?/, "");
  if (path === "" || path === "overview") {
    return "overview";
  }
  return isPageId(path) ? path : "overview";
}
