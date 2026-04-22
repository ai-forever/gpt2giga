const REPO_DOCS_BASE = "https://github.com/ai-forever/gpt2giga/blob/main/docs";

export const DOCS_INDEX_URL = `${REPO_DOCS_BASE}/README.md`;
export const CONFIGURATION_GUIDE_URL = `${REPO_DOCS_BASE}/configuration.md`;
export const OPERATOR_GUIDE_URL = `${REPO_DOCS_BASE}/operator-guide.md`;
export const API_COMPATIBILITY_URL = `${REPO_DOCS_BASE}/api-compatibility.md`;
export const UPGRADE_GUIDE_URL = `${REPO_DOCS_BASE}/upgrade-0.x-to-1.0.md`;

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

export const CANONICAL_DOC_LINKS = {
  index: DOCS_INDEX_URL,
  configuration: CONFIGURATION_GUIDE_URL,
  compatibility: API_COMPATIBILITY_URL,
  upgrade: UPGRADE_GUIDE_URL,
} as const;
