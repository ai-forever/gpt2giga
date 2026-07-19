import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const styles = readFileSync(fileURLToPath(new URL("./styles.css", import.meta.url)), "utf8");

describe("workbench viewport containment", () => {
  it("keeps a resized composer inside the workbench viewport", () => {
    expect(styles).toMatch(/\.workbench-layout \{[^}]*overflow: hidden;/);
    expect(styles).toMatch(/\.composer textarea \{[^}]*max-height: min\(260px, 40vh\);/);
    expect(styles).toMatch(/\.composer textarea \{[^}]*overflow-y: auto;/);
  });
});
