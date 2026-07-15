export interface SessionSummary {
  id: string;
  title: string;
  updated_at: string;
  pinned: boolean;
  archived: boolean;
}

export interface RunSummary {
  id: string;
  session_id: string;
  status: string;
  updated_at: string;
}

export interface CursorPage<T> {
  has_more: boolean;
  next_cursor: string | null;
  snapshot_revision: string;
  byte_count: number;
  items: T[];
}

export interface SessionIndexResponse {
  sessions: SessionSummary[];
  has_more: boolean;
  next_cursor: string | null;
  snapshot_revision: string;
  byte_count: number;
}

export interface SessionOverviewResponse {
  session: SessionSummary;
  snapshot_revision: string;
  projections: Record<string, string>;
}

export interface RunOverviewResponse {
  run: RunSummary;
  snapshot_revision: string;
  projections: Record<string, string>;
}

export interface RunsCenterResponse {
  runs: unknown[];
  next_cursor: string | null;
}

export class CockpitApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "CockpitApiError";
    this.status = status;
  }
}

export async function fetchCockpit<T>(
  path: string,
  signal: AbortSignal,
): Promise<T> {
  const response = await fetch(path, {
    headers: { Accept: "application/json" },
    signal,
  });
  if (!response.ok) {
    throw new CockpitApiError(response.status, await response.text());
  }
  return (await response.json()) as T;
}

export function withQuery(
  path: string,
  values: Readonly<Record<string, string | number | boolean | null | undefined>>,
): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (value !== null && value !== undefined && value !== "") {
      search.set(key, String(value));
    }
  }
  const query = search.toString();
  return query ? `${path}?${query}` : path;
}
