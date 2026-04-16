export type TrafficPage =
  | "traffic"
  | "traffic-requests"
  | "traffic-errors"
  | "traffic-usage";

export interface TrafficFilters {
  limit: string;
  requestId: string;
  provider: string;
  endpoint: string;
  method: string;
  statusCode: string;
  model: string;
  errorType: string;
  source: string;
  apiKeyName: string;
}

export interface DefinitionItem {
  label: string;
  value: string;
  note?: string;
}

export interface TrafficSelection {
  requestId: string | null;
  counterpartKind: "request" | "error" | null;
  counterpartIndex: number | null;
}

export type TrafficEvent = Record<string, unknown>;
export type TrafficDetailKind = "request" | "error" | "key" | "provider";
export type UsageEntry = Record<string, unknown>;

export const DEFAULT_LIMIT = "25";
