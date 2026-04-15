import { renderFilesBatches } from "./render-files-batches.js";
import { renderKeys } from "./render-keys.js";
import { renderLogs } from "./render-logs.js";
import { renderOverview } from "./render-overview.js";
import { renderPlayground } from "./render-playground.js";
import { renderProviders } from "./render-providers.js";
import { renderSettings } from "./render-settings.js";
import { renderSetup } from "./render-setup.js";
import { renderSystem } from "./render-system.js";
import { renderTraffic } from "./render-traffic.js";
export const PAGE_RENDERERS = {
    overview: renderOverview,
    setup: renderSetup,
    settings: renderSettings,
    keys: renderKeys,
    logs: renderLogs,
    playground: renderPlayground,
    traffic: renderTraffic,
    providers: renderProviders,
    "files-batches": renderFilesBatches,
    system: renderSystem,
};
