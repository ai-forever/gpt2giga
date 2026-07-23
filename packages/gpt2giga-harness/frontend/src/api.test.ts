import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchCockpit } from "./api";

describe("Cockpit API errors", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("projects FastAPI detail as a recovery-friendly error message", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            detail:
              "The durable worker is offline. Start it with `giga worker start`, then retry.",
          }),
          {
            headers: { "Content-Type": "application/json" },
            status: 409,
          },
        ),
      ),
    );

    await expect(fetchCockpit("/api/automation")).rejects.toMatchObject({
      message:
        "The durable worker is offline. Start it with `giga worker start`, then retry.",
      status: 409,
    });
  });
});
