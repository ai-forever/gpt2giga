export const PAGE_META = {
    overview: {
        eyebrow: "Overview",
        title: "Gateway overview",
        subtitle: "Health, setup readiness, usage volume, and operator warnings in one place.",
    },
    setup: {
        eyebrow: "Setup",
        title: "Bootstrap and first-run flow",
        subtitle: "Persist control-plane config, configure GigaChat, and close out PROD bootstrap access from one guided page.",
    },
    settings: {
        eyebrow: "Settings",
        title: "Configuration editor",
        subtitle: "Application, GigaChat, and security settings with persisted storage, diffs, and rollback.",
    },
    keys: {
        eyebrow: "Keys",
        title: "API key control",
        subtitle: "Create, rotate, and revoke gateway keys without touching environment files.",
    },
    logs: {
        eyebrow: "Logs",
        title: "Live log surface",
        subtitle: "Tail logs, stream new lines, and inspect failures without leaving the console.",
    },
    playground: {
        eyebrow: "Playground",
        title: "Manual request playground",
        subtitle: "Test OpenAI, Anthropic, and Gemini-compatible calls directly against this proxy.",
    },
    traffic: {
        eyebrow: "Traffic",
        title: "Recent request and error traffic",
        subtitle: "Recent request feeds, usage summaries, and recent errors from runtime observability.",
    },
    providers: {
        eyebrow: "Providers",
        title: "Provider surfaces",
        subtitle: "Enabled providers, backend posture, and live capability coverage in one view.",
    },
    "files-batches": {
        eyebrow: "Files & Batches",
        title: "Files and batch jobs",
        subtitle: "Upload JSONL inputs, inspect stored files, and launch OpenAI-compatible batch jobs.",
    },
    system: {
        eyebrow: "System",
        title: "System posture",
        subtitle: "Readiness, runtime health, effective config, and diagnostics for this gateway.",
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
