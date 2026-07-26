import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchCockpit, mutateCockpit } from "./api";

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

  it("marks browser mutations with the same-origin CSRF header", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await mutateCockpit("/api/example", { enabled: true });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/example",
      expect.objectContaining({
        headers: expect.objectContaining({ "X-GigaLoom-CSRF": "1" }),
        method: "POST",
      }),
    );
  });
});
