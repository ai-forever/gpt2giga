import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const styles = readFileSync(fileURLToPath(new URL("./styles.css", import.meta.url)), "utf8");
const shell = readFileSync(fileURLToPath(new URL("./AppShell.tsx", import.meta.url)), "utf8");
const workbench = readFileSync(
  fileURLToPath(new URL("./surfaces/workbench.tsx", import.meta.url)),
  "utf8",
);

describe("workbench viewport containment", () => {
  it("keeps a resized composer inside the workbench viewport", () => {
    expect(styles).toMatch(/\.workbench-layout \{[^}]*overflow: hidden;/);
    expect(styles).toMatch(/\.composer textarea \{[^}]*max-height: min\(260px, 40vh\);/);
    expect(styles).toMatch(/\.composer textarea \{[^}]*overflow-y: auto;/);
  });

  it("locks document scrolling for desktop Workbench routes only", () => {
    expect(shell).toContain('activeSurface === "work"');
    expect(shell).toContain('classList.toggle("workbench-scroll-lock", workbenchActive)');
    expect(shell).toContain("root.scrollTop = 0");
    expect(styles).toMatch(/@media \(min-width: 761px\) \{/);
    expect(styles).toContain("html.workbench-scroll-lock body");
    expect(styles).toContain("html.workbench-scroll-lock #root");
    expect(styles).toMatch(/html\.workbench-scroll-lock #root \{[^}]*overflow: hidden;/);
  });

  it("keeps streaming runtime-owned and tool selection in the compact composer flow", () => {
    expect(workbench).not.toContain("advancedConfig.stream");
    expect(workbench).not.toContain('message(locale, "streamResponse")');
    expect(workbench).toContain('className="composer-tool-picker"');
    expect(workbench).toContain("admittedBuiltinToolSelection(");
    expect(workbench).toContain('message(locale, "toolsAndIntegrations")');
  });
});
