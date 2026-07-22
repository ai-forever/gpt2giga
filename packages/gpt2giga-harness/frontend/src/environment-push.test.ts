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
const api = readFileSync(fileURLToPath(new URL("./api.ts", import.meta.url)), "utf8");
const styles = readFileSync(fileURLToPath(new URL("./styles.css", import.meta.url)), "utf8");

describe("governed Environment push flow", () => {
  it("keeps preview, approval, and apply on backend-owned routes", () => {
    expect(workbench).toContain('"/api/environment/push/preview"');
    expect(workbench).toContain('"/api/environment/push/apply"');
    expect(workbench).toContain("environmentPushPreview");
    expect(workbench).toContain("openInbox(\"approvals\")");
  });

  it("shows exact remote state and permissions before approval", () => {
    expect(inbox).toContain('approval.action === "git.push"');
    expect(approvalPreview).toContain("PushApprovalPreview");
    expect(approvalPreview).toContain("preview?.remote_head");
    expect(approvalPreview).toContain("permissionRecord");
    expect(api).toContain("force_update: boolean");
  });

  it("links the exact remote commit and run evidence after completion", () => {
    expect(workbench).toContain("remote_commit_url");
    expect(workbench).toContain("run_evidence_url");
    expect(styles).toContain(".environment-push-links");
  });
});
