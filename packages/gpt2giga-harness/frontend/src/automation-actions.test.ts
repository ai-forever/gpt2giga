import { describe, expect, it } from "vitest";

import {
  createAutomationSubmissionKey,
  planAutomationAction,
  projectAutomationActionResult,
} from "./automation-actions";

describe("Automation action contracts", () => {
  it("makes unavailable agents explicit and schedules test before run-now", () => {
    expect(
      planAutomationAction("agents", {
        id: "reviewer",
        title: "Reviewer",
        harnessId: "codex-cli",
        mode: "read",
        model: null,
        queueable: false,
        unavailableReason: "Codex CLI is unavailable",
      }),
    ).toMatchObject({
      kind: "agent_run",
      disabledReason: "Codex CLI is unavailable",
      prompt: "required",
    });
    expect(
      planAutomationAction("workflows", {
        id: "review",
        title: "Review",
        trigger: "manual",
        stepCount: 2,
        lastRunStatus: null,
        lastRunAt: null,
        workerOnline: false,
      }),
    ).toMatchObject({
      kind: "workflow_run",
      disabledReason: "worker_offline",
    });
    expect(
      planAutomationAction("schedules", {
        id: "nightly",
        title: "Nightly",
        target: "workflow:review",
        status: "paused",
        nextRunAt: null,
        workerOnline: false,
        tested: false,
      }),
    ).toMatchObject({ kind: "schedule_test", disabledReason: null });
  });

  it("projects exact retained identities from every native action response", () => {
    expect(
      projectAutomationActionResult({
        session: { id: "session_agent" },
        run: { id: "run_agent" },
      }),
    ).toMatchObject({ runId: "run_agent", sessionId: "session_agent" });
    expect(
      projectAutomationActionResult({
        run: {
          id: "workflow_review",
          session_id: "session_workflow",
          steps: [{ outputs: { run_id: "run_child" } }],
        },
      }),
    ).toMatchObject({
      runId: "run_child",
      sessionId: "session_workflow",
      workflowRunId: "workflow_review",
    });
    expect(
      projectAutomationActionResult({
        approval_required: true,
        approval: { id: "approval_schedule" },
      }),
    ).toMatchObject({ approvalId: "approval_schedule", runId: null });
  });

  it("creates bounded caller-owned submission keys", () => {
    const key = createAutomationSubmissionKey("workflows", "review-team");
    expect(key).toMatch(/^cockpit:workflows:review-team:/);
    expect(key.length).toBeLessThanOrEqual(200);
  });
});
