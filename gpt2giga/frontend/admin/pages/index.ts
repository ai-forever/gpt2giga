import type { AdminApp } from "../app";
import type { PageId } from "../types";
import { renderFilesBatches } from "./render-files-batches";
import { renderKeys } from "./render-keys";
import { renderLogs } from "./render-logs";
import { renderOverview } from "./render-overview";
import { renderPlayground } from "./render-playground";
import { renderProviders } from "./render-providers";
import { renderSettings } from "./render-settings";
import { renderSetup } from "./render-setup";
import { renderSystem } from "./render-system";
import { renderTraffic } from "./render-traffic";

export const PAGE_RENDERERS: Record<
  PageId,
  (app: AdminApp, token: number) => Promise<void>
> = {
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
