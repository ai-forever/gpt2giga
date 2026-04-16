import { renderFilesBatches } from "./render-files-batches.js";
import { renderKeys } from "./render-keys.js";
import { renderLogs } from "./render-logs.js";
import { renderOverview } from "./render-overview.js";
import { renderPlayground } from "./render-playground.js";
import { renderProviders } from "./render-providers.js";
import { renderSettings, renderSettingsApplication, renderSettingsGigachat, renderSettingsHistory, renderSettingsObservability, renderSettingsSecurity, } from "./render-settings.js";
import { renderSetup, renderSetupApplication, renderSetupClaim, renderSetupGigachat, renderSetupSecurity, } from "./render-setup.js";
import { renderSystem } from "./render-system.js";
import { renderTraffic } from "./render-traffic.js";
export const PAGE_RENDERERS = {
    overview: renderOverview,
    setup: renderSetup,
    "setup-claim": renderSetupClaim,
    "setup-application": renderSetupApplication,
    "setup-gigachat": renderSetupGigachat,
    "setup-security": renderSetupSecurity,
    settings: renderSettings,
    "settings-application": renderSettingsApplication,
    "settings-observability": renderSettingsObservability,
    "settings-gigachat": renderSettingsGigachat,
    "settings-security": renderSettingsSecurity,
    "settings-history": renderSettingsHistory,
    keys: renderKeys,
    logs: renderLogs,
    playground: renderPlayground,
    traffic: renderTraffic,
    "traffic-requests": renderTraffic,
    "traffic-errors": renderTraffic,
    "traffic-usage": renderTraffic,
    providers: renderProviders,
    "files-batches": renderFilesBatches,
    files: renderFilesBatches,
    batches: renderFilesBatches,
    system: renderSystem,
};
