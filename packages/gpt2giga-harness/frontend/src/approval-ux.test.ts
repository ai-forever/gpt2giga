import { describe, expect, it } from "vitest";

import type { ApprovalRequest, RunPreflightResponse } from "./api";
import {
  approvalDecisionPayload,
  decisionLabelKey,
  enabledApprovalOptions,
  permissionSimulationRows,
} from "./approval-ux";

describe("approval UX", () => {
  it("submits only server-admitted decision lifetimes", () => {
    const approval = {
      id: "approval-1",
      ux: {
        decision_options: [
          {
            decision: "deny",
            enabled: true,
            expires_in_seconds: null,
            lifetime: "operation",
            why: "always",
          },
          {
            decision: "allow_session",
            enabled: true,
            expires_in_seconds: null,
            lifetime: "session",
            why: "session",
          },
          {
            decision: "allow_project",
            enabled: false,
            expires_in_seconds: 3600,
            lifetime: "persisted_policy",
            why: "blocked",
          },
        ],
      },
    } as ApprovalRequest;

    const options = enabledApprovalOptions(approval);
    expect(options.map((option) => option.decision)).toEqual(["deny", "allow_session"]);
    expect(approvalDecisionPayload(options[1]!)).toEqual({ decision: "allow_session" });
    expect(decisionLabelKey(options[1]!.decision)).toBe("approveSession");
  });

  it("projects side-effect-free simulation evidence into inspectable rows", () => {
    const simulation = {
      outcomes: [
        {
          domain: "network",
          action: "network.connect",
          prediction: "approval_required",
          occurrence: "required_before_start",
          control_owner: "harness_policy",
          reason_code: "provider_route_required",
        },
      ],
    } as RunPreflightResponse["preflight"]["permission_simulation"];

    expect(permissionSimulationRows(simulation)).toEqual([
      {
        action: "network.connect",
        consequence: "provider_route_required",
        occurrence: "required_before_start",
        owner: "harness_policy",
        prediction: "approval_required",
      },
    ]);
  });
});
