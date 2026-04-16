export const WORKFLOW_META = {
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
export const WORKFLOW_ORDER = ["start", "configure", "observe", "diagnose"];
export const PAGE_META = {
    overview: {
        eyebrow: "Overview",
        title: "Gateway overview",
        subtitle: "Health, setup readiness, usage volume, and operator warnings in one place.",
        workflow: "start",
        navDescription: "Summary-first posture view with the next operator action already narrowed down.",
    },
    setup: {
        eyebrow: "Setup",
        title: "Bootstrap and first-run flow",
        subtitle: "Persist control-plane config, configure GigaChat, and close out PROD bootstrap access from one guided page.",
        workflow: "start",
        navDescription: "Guided bootstrap flow for persisted config, GigaChat auth, and security closure.",
    },
    settings: {
        eyebrow: "Settings",
        title: "Configuration editor",
        subtitle: "Application, GigaChat, and security settings with persisted storage, diffs, and rollback.",
        workflow: "configure",
        navDescription: "Edit persisted control-plane sections, including observability and restart semantics.",
    },
    keys: {
        eyebrow: "Keys",
        title: "API key control",
        subtitle: "Create, rotate, and revoke gateway keys without touching environment files.",
        workflow: "configure",
        navDescription: "Manage global and scoped gateway auth without editing env files by hand.",
    },
    logs: {
        eyebrow: "Logs",
        title: "Live log surface",
        subtitle: "Tail logs, stream new lines, and inspect failures without leaving the console.",
        workflow: "observe",
        navDescription: "Deep-dive into one request or failure after Traffic narrows the scope.",
    },
    playground: {
        eyebrow: "Playground",
        title: "Manual request playground",
        subtitle: "Test OpenAI, Anthropic, and Gemini-compatible calls directly against this proxy.",
        workflow: "start",
        navDescription: "Smoke the mounted compatibility routes before exposing them to real clients.",
    },
    traffic: {
        eyebrow: "Traffic",
        title: "Recent request and error traffic",
        subtitle: "Recent request feeds, usage summaries, and recent errors from runtime observability.",
        workflow: "observe",
        navDescription: "Summary-first request feed with direct handoff into matching log context.",
    },
    providers: {
        eyebrow: "Providers",
        title: "Provider surfaces",
        subtitle: "Enabled providers, backend posture, and live capability coverage in one view.",
        workflow: "diagnose",
        navDescription: "Compare configured providers against mounted routes and live capability coverage.",
    },
    "files-batches": {
        eyebrow: "Files & Batches",
        title: "Files and batch jobs",
        subtitle: "Upload JSONL inputs, inspect stored files, and launch OpenAI-compatible batch jobs.",
        workflow: "diagnose",
        navDescription: "Inspect stored inputs, batch jobs, and advanced workbench state from one place.",
    },
    system: {
        eyebrow: "System",
        title: "System posture",
        subtitle: "Readiness, runtime health, effective config, and diagnostics for this gateway.",
        workflow: "diagnose",
        navDescription: "Runtime, config, and route diagnostics when the operator story feels inconsistent.",
    },
};
export const PAGE_ORDER = Object.keys(PAGE_META);
export function pathForPage(page) {
    return page === "overview" ? "/admin" : `/admin/${page}`;
}
export function isPageId(value) {
    return PAGE_ORDER.includes(value);
}
export function pageFromLocation(location) {
    const queryPage = new URLSearchParams(location.search).get("tab")?.trim();
    if (queryPage && isPageId(queryPage)) {
        return queryPage;
    }
    const path = location.pathname.replace(/^\/admin\/?/, "");
    if (path === "" || path === "overview") {
        return "overview";
    }
    return isPageId(path) ? path : "overview";
}
export function isConsolePathname(pathname) {
    return pathname === "/admin" || PAGE_ORDER.some((page) => pathForPage(page) === pathname);
}
export function pagesForWorkflow(workflow) {
    return PAGE_ORDER.filter((page) => PAGE_META[page].workflow === workflow);
}
