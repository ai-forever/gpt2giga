const REPO_DOCS_BASE = "https://github.com/ai-forever/gpt2giga/blob/main/docs";

export const OPERATOR_GUIDE_URL = `${REPO_DOCS_BASE}/operator-guide.md`;

export function buildOperatorGuideUrl(anchor?: string): string {
  return anchor ? `${OPERATOR_GUIDE_URL}#${anchor}` : OPERATOR_GUIDE_URL;
}

export const OPERATOR_GUIDE_LINKS = {
  overview: buildOperatorGuideUrl(),
  traffic: buildOperatorGuideUrl("traffic-summary-to-request-scope"),
  logs: buildOperatorGuideUrl("logs-deep-dive-and-live-tail"),
  providers: buildOperatorGuideUrl("provider-surface-diagnostics"),
  filesBatches: buildOperatorGuideUrl("files-and-batches-lifecycle"),
  troubleshooting: buildOperatorGuideUrl("troubleshooting-handoff-map"),
  rolloutV2: buildOperatorGuideUrl("rollout-backend-v2"),
} as const;
