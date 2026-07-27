import type { ApprovalDecisionOption, ApprovalRequest, RunPreflightResponse } from "./api";

export function approvalDecisionPayload(option: ApprovalDecisionOption) {
  return {
    decision: option.decision,
    ...(option.expires_in_seconds === null
      ? {}
      : { expires_in_seconds: option.expires_in_seconds }),
  };
}

export function enabledApprovalOptions(approval: ApprovalRequest) {
  return approval.ux?.decision_options.filter((option) => option.enabled) ?? [
    {
      decision: "deny",
      enabled: true,
      expires_in_seconds: null,
      lifetime: "operation",
      why: "legacy_approval_projection",
    },
    {
      decision: "allow_once",
      enabled: true,
      expires_in_seconds: null,
      lifetime: "operation",
      why: "legacy_approval_projection",
    },
  ];
}

export function permissionSimulationRows(
  simulation: RunPreflightResponse["preflight"]["permission_simulation"],
) {
  if (simulation === undefined) return [];
  return simulation.outcomes.map((outcome) => ({
    action: outcome.action ?? outcome.domain,
    consequence: outcome.reason_code,
    occurrence: outcome.occurrence,
    owner: outcome.control_owner,
    prediction: outcome.prediction,
  }));
}

export function decisionLabelKey(decision: string) {
  if (decision === "deny") return "deny";
  if (decision === "allow_session") return "approveSession";
  if (decision === "allow_project") return "approveReviewedPolicy";
  return "approveOnce";
}
