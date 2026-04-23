import { asArray, asRecord } from "../../utils.js";
import { buildEventQuery, buildUsageKeysQuery, buildUsageProvidersQuery, } from "./serializers.js";
export async function loadTrafficPageData(app, filters) {
    const [requestsPayload, errorsPayload, usageKeysPayload, usageProvidersPayload] = await Promise.all([
        app.api.json(`/admin/api/requests/recent?${buildEventQuery(filters)}`),
        app.api.json(`/admin/api/errors/recent?${buildEventQuery(filters)}`),
        app.api.json(`/admin/api/usage/keys?${buildUsageKeysQuery(filters)}`),
        app.api.json(`/admin/api/usage/providers?${buildUsageProvidersQuery(filters)}`),
    ]);
    return {
        requestsPayload,
        errorsPayload,
        usageKeysPayload,
        usageProvidersPayload,
        requestEvents: asArray(requestsPayload.events).slice().reverse(),
        errorEvents: asArray(errorsPayload.events).slice().reverse(),
        keyEntries: asArray(usageKeysPayload.entries),
        providerEntries: asArray(usageProvidersPayload.entries),
        providerSummary: asRecord(usageProvidersPayload.summary),
    };
}
