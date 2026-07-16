import { QueryClient } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { SessionOverviewResponse } from "./api";
import {
  cancelRequestScope,
  refreshSessionAfterRunStart,
  refreshSessionRevision,
  requestKeys,
  runProjectionOptions,
  sessionOverviewOptions,
  updateSessionOverview,
} from "./request-graph";

afterEach(() => {
  vi.restoreAllMocks();
});

function queryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 0 } },
  });
}

function sessionResponse(id: string, title = id): SessionOverviewResponse {
  return {
    projections: {},
    session: {
      archived: false,
      id,
      pinned: false,
      title,
      updated_at: "2026-07-16T00:00:00Z",
    },
    snapshot_revision: `revision-${id}`,
  };
}

describe("Cockpit request graph", () => {
  it("deduplicates concurrent reads with one stable query key", async () => {
    let resolveResponse: ((response: Response) => void) | undefined;
    const response = new Promise<Response>((resolve) => {
      resolveResponse = resolve;
    });
    const fetchMock = vi.spyOn(globalThis, "fetch").mockReturnValue(response);
    const client = queryClient();
    const options = sessionOverviewOptions("session-one");

    const first = client.fetchQuery(options);
    const second = client.fetchQuery(options);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    resolveResponse?.(
      new Response(JSON.stringify(sessionResponse("session-one")), {
        headers: { "Content-Type": "application/json" },
      }),
    );
    await expect(Promise.all([first, second])).resolves.toHaveLength(2);
  });

  it("forwards cancellation to fetch when a route scope becomes stale", async () => {
    let observedSignal: AbortSignal | undefined;
    vi.spyOn(globalThis, "fetch").mockImplementation((_input, init) => {
      observedSignal = init?.signal ?? undefined;
      return new Promise<Response>((_resolve, reject) => {
        observedSignal?.addEventListener("abort", () => {
          reject(new DOMException("aborted", "AbortError"));
        });
      });
    });
    const client = queryClient();
    const pending = client.fetchQuery(sessionOverviewOptions("session-stale"));

    await Promise.resolve();
    await cancelRequestScope(client, requestKeys.sessionScope("session-stale"));

    expect(observedSignal?.aborted).toBe(true);
    await expect(pending).rejects.toBeDefined();
  });

  it("keeps out-of-order session responses isolated by identity", async () => {
    const resolvers = new Map<string, (response: Response) => void>();
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      return new Promise<Response>((resolve) => {
        resolvers.set(url, resolve);
      });
    });
    const client = queryClient();
    const first = client.fetchQuery(sessionOverviewOptions("first"));
    const second = client.fetchQuery(sessionOverviewOptions("second"));
    await Promise.resolve();

    resolvers.get("/api/cockpit/sessions/second")?.(
      new Response(JSON.stringify(sessionResponse("second"))),
    );
    await second;
    resolvers.get("/api/cockpit/sessions/first")?.(
      new Response(JSON.stringify(sessionResponse("first"))),
    );
    await first;

    expect(
      client.getQueryData<SessionOverviewResponse>(
        requestKeys.sessionOverview("second"),
      )?.session.id,
    ).toBe("second");
    expect(
      client.getQueryData<SessionOverviewResponse>(
        requestKeys.sessionOverview("first"),
      )?.session.id,
    ).toBe("first");
  });

  it("updates one cache entry without invalidating unrelated sessions", () => {
    const client = queryClient();
    client.setQueryData(requestKeys.sessionOverview("first"), sessionResponse("first"));
    client.setQueryData(
      requestKeys.sessionOverview("second"),
      sessionResponse("second"),
    );

    updateSessionOverview(client, "first", (current) => ({
      ...current,
      session: { ...current.session, title: "updated" },
    }));

    expect(
      client.getQueryData<SessionOverviewResponse>(
        requestKeys.sessionOverview("first"),
      )?.session.title,
    ).toBe("updated");
    expect(
      client.getQueryData<SessionOverviewResponse>(
        requestKeys.sessionOverview("second"),
      )?.session.title,
    ).toBe("second");
  });

  it("refreshes retained messages immediately after a run starts", async () => {
    const client = queryClient();
    const invalidate = vi.spyOn(client, "invalidateQueries");

    await refreshSessionAfterRunStart(client, "session-one");

    expect(invalidate).toHaveBeenCalledTimes(2);
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: requestKeys.sessionProjection("session-one", "messages"),
    });
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: requestKeys.runsCenter(),
    });
  });

  it("refreshes the selected title and sidebar from a session revision", async () => {
    const client = queryClient();
    const invalidate = vi.spyOn(client, "invalidateQueries");

    await refreshSessionRevision(client, "session-one");

    expect(invalidate).toHaveBeenCalledTimes(2);
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: requestKeys.sessionOverview("session-one"),
    });
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: requestKeys.sessionIndex(),
    });
  });

  it("keeps heavy evidence behind explicit lazy projection URLs", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ report: { text: "bounded" } })),
    );
    const client = queryClient();

    await client.fetchQuery(runProjectionOptions("run 1", "report"));

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/cockpit/runs/run%201/report",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
  });
});
