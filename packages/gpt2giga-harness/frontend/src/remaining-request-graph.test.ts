import { QueryClient } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  integrationFlowOptions,
  mcpInventoryOptions,
} from "./remaining-request-graph";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("remaining surface request graph", () => {
  it("loads the plugin library without model, settings, or harness probes", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      const payload = url === "/api/integrations"
        ? { sources: [], targets: [], catalog: [], flows: [], content_free: true }
        : { servers: [] };
      return Promise.resolve(new Response(JSON.stringify(payload)));
    });
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: 0 } },
    });

    await Promise.all([
      client.fetchQuery(integrationFlowOptions()),
      client.fetchQuery(mcpInventoryOptions()),
    ]);

    expect(fetchMock.mock.calls.map(([input]) => String(input)).sort()).toEqual([
      "/api/integrations",
      "/api/tool-servers",
    ]);
  });
});
