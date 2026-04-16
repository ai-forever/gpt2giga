import type { AdminApp } from "../../app.js";
import { asArray, asRecord } from "../../utils.js";
import {
  buildEventQuery,
  buildUsageKeysQuery,
  buildUsageProvidersQuery,
} from "./serializers.js";
import type {
  TrafficEvent,
  TrafficFilters,
  UsageEntry,
} from "./state.js";

export interface TrafficPageData {
  requestsPayload: Record<string, unknown>;
  errorsPayload: Record<string, unknown>;
  usageKeysPayload: Record<string, unknown>;
  usageProvidersPayload: Record<string, unknown>;
  requestEvents: TrafficEvent[];
  errorEvents: TrafficEvent[];
  keyEntries: UsageEntry[];
  providerEntries: UsageEntry[];
  providerSummary: Record<string, unknown>;
}

export async function loadTrafficPageData(
  app: AdminApp,
  filters: TrafficFilters,
): Promise<TrafficPageData> {
  const [requestsPayload, errorsPayload, usageKeysPayload, usageProvidersPayload] = await Promise.all([
    app.api.json<Record<string, unknown>>(`/admin/api/requests/recent?${buildEventQuery(filters)}`),
    app.api.json<Record<string, unknown>>(`/admin/api/errors/recent?${buildEventQuery(filters)}`),
    app.api.json<Record<string, unknown>>(`/admin/api/usage/keys?${buildUsageKeysQuery(filters)}`),
    app.api.json<Record<string, unknown>>(
      `/admin/api/usage/providers?${buildUsageProvidersQuery(filters)}`,
    ),
  ]);

  return {
    requestsPayload,
    errorsPayload,
    usageKeysPayload,
    usageProvidersPayload,
    requestEvents: asArray<TrafficEvent>(requestsPayload.events),
    errorEvents: asArray<TrafficEvent>(errorsPayload.events),
    keyEntries: asArray<UsageEntry>(usageKeysPayload.entries),
    providerEntries: asArray<UsageEntry>(usageProvidersPayload.entries),
    providerSummary: asRecord(usageProvidersPayload.summary),
  };
}
