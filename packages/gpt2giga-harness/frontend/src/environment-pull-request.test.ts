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

describe("governed Environment pull-request flow", () => {
  it("keeps preview, approval, and apply on backend-owned routes", () => {
    expect(workbench).toContain('"/api/environment/pull-request/preview"');
    expect(workbench).toContain('"/api/environment/pull-request/apply"');
    expect(workbench).toContain("environmentPullRequestPreview");
    expect(workbench).toContain('openInbox("approvals")');
  });

  it("shows exact repository, refs, content, and permissions before approval", () => {
    expect(inbox).toContain('approval.action === "github.pull_request.create"');
    expect(approvalPreview).toContain("PullRequestApprovalPreview");
    expect(approvalPreview).toContain("preview?.source_head");
    expect(approvalPreview).toContain("preview?.base_head");
    expect(approvalPreview).toContain("preview?.title");
    expect(api).toContain("EnvironmentPullRequestPreview");
  });

  it("links the exact PR, commit, checks, and run evidence", () => {
    expect(workbench).toContain("pull_request_url");
    expect(workbench).toContain("commit_url");
    expect(workbench).toContain("checks_url");
    expect(workbench).toContain("run_evidence_url");
    expect(styles).toContain(".environment-pull-request-action");
  });
});
