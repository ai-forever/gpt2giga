import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const workbench = readFileSync(
  fileURLToPath(new URL("./surfaces/workbench.tsx", import.meta.url)),
  "utf8",
);
const inbox = readFileSync(
  fileURLToPath(new URL("./components/InboxDrawer.tsx", import.meta.url)),
  "utf8",
);
const approvalPreview = readFileSync(
  fileURLToPath(new URL("./inspectors/InspectorFrame.tsx", import.meta.url)),
  "utf8",
);
const styles = readFileSync(fileURLToPath(new URL("./styles.css", import.meta.url)), "utf8");

describe("governed Environment commit flow", () => {
  it("keeps preview, approval, and apply on backend-owned routes", () => {
    expect(workbench).toContain('"/api/environment/commit/preview"');
    expect(workbench).toContain('"/api/environment/commit/apply"');
    expect(workbench).toContain("openInbox(\"approvals\")");
    expect(workbench).toContain("environmentCommitPreview");
  });

  it("shows the exact author, message, HEAD, and diff before approval", () => {
    expect(inbox).toContain('approval.action === "git.commit"');
    expect(inbox).toContain('import("../inspectors/InspectorFrame")');
    expect(approvalPreview).toContain("authorRecord.email");
    expect(approvalPreview).toContain("preview?.message");
    expect(approvalPreview).toContain("preview?.diff_sha256");
  });

  it("stacks bounded commit fields at mobile width", () => {
    expect(styles).toContain(".environment-commit-form");
    expect(styles).toContain(".mobile-environment .environment-commit-form > div { grid-template-columns: 1fr; }");
  });
});
