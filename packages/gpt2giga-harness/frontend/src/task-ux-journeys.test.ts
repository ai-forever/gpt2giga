import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { surfaceForPath } from "./navigation";

type Journey = {
  id: string;
  web_route: string;
  web_surface: string;
  api_routes: string[];
  other_surfaces: string[];
  authority: {
    ceiling: string;
    mutation: string;
  };
  outcomes: string[];
};

const fixture = JSON.parse(
  readFileSync(
    fileURLToPath(
      new URL(
        "../../../../tests/harness/fixtures/task_ux_journeys.json",
        import.meta.url,
      ),
    ),
    "utf8",
  ),
) as { schema_version: number; journeys: Journey[] };

describe("task-based UX golden journeys", () => {
  it("keeps each journey on its semantic Cockpit surface", () => {
    expect(fixture.schema_version).toBe(1);
    expect(
      fixture.journeys.map((journey) => [
        journey.id,
        surfaceForPath(
          journey.web_route
            .replace("{run_id}", "run_fixture")
            .replace("{workflow_id}", "workflow_fixture"),
        ),
      ]),
    ).toEqual(
      fixture.journeys.map((journey) => [
        journey.id,
        journey.web_surface,
      ]),
    );
  });

  it("asserts outcomes and authority without preserving widget structure", () => {
    const serialized = JSON.stringify(fixture);

    expect(fixture.journeys).toHaveLength(8);
    for (const journey of fixture.journeys) {
      expect(journey.api_routes.length).toBeGreaterThan(0);
      expect(journey.outcomes.length).toBeGreaterThan(0);
      expect(journey.authority.ceiling).toBeTruthy();
      expect(journey.authority.mutation).toBeTruthy();
    }
    expect(serialized).not.toMatch(
      /selector|data-testid|widget|checkbox|drawer|headless|transport/i,
    );
  });
});
