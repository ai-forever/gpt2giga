import { asArray, asRecord } from "../../utils.js";
import type { SetupNextStep, SetupPage, SetupSection } from "./types.js";

export interface SetupPageState {
  activeSection: SetupSection | null;
  applicationValues: Record<string, unknown>;
  bootstrap: Record<string, unknown>;
  claim: Record<string, unknown>;
  currentPage: SetupPage;
  gigachatValues: Record<string, unknown>;
  globalKey: Record<string, unknown>;
  nextStep: SetupNextStep;
  observabilityValues: Record<string, unknown>;
  persisted: boolean;
  persistedUpdatedAt: unknown;
  runtime: Record<string, unknown>;
  scopedKeys: Record<string, unknown>[];
  securityValues: Record<string, unknown>;
  setup: Record<string, unknown>;
  warnings: string[];
}

export function buildSetupPageState(
  currentPage: SetupPage,
  payloads: {
    application: Record<string, unknown>;
    gigachat: Record<string, unknown>;
    keys: Record<string, unknown>;
    observability: Record<string, unknown>;
    runtime: Record<string, unknown>;
    security: Record<string, unknown>;
    setup: Record<string, unknown>;
  },
): SetupPageState {
  const claim = asRecord(payloads.setup.claim);

  return {
    activeSection: sectionForSetupPage(currentPage),
    applicationValues: asRecord(payloads.application.values),
    bootstrap: asRecord(payloads.setup.bootstrap),
    claim,
    currentPage,
    gigachatValues: asRecord(payloads.gigachat.values),
    globalKey: asRecord(asRecord(payloads.keys.global)),
    nextStep: getNextRecommendedSetupPage(payloads.setup),
    observabilityValues: asRecord(payloads.observability.values),
    persisted: Boolean(payloads.setup.persisted),
    persistedUpdatedAt: payloads.setup.updated_at,
    runtime: payloads.runtime,
    scopedKeys: asArray<Record<string, unknown>>(payloads.keys.scoped),
    securityValues: asRecord(payloads.security.values),
    setup: payloads.setup,
    warnings: asArray<string>(payloads.setup.warnings),
  };
}

export function sectionForSetupPage(page: SetupPage): SetupSection | null {
  switch (page) {
    case "setup-claim":
      return "claim";
    case "setup-application":
      return "application";
    case "setup-gigachat":
      return "gigachat";
    case "setup-security":
      return "security";
    default:
      return null;
  }
}

export function getNextRecommendedSetupPage(
  setup: Record<string, unknown>,
): SetupNextStep {
  const claim = asRecord(setup.claim);
  if (claim.required && !claim.claimed) {
    return {
      href: "/admin/setup-claim",
      label: "Open claim step",
      note: "Claim the bootstrap session first.",
    };
  }
  if (setup.persistence_enabled !== false && !setup.persisted) {
    return {
      href: "/admin/setup-application",
      label: "Open application step",
      note: "Persist the baseline runtime posture first.",
    };
  }
  if (!setup.gigachat_ready) {
    return {
      href: "/admin/setup-gigachat",
      label: "Open GigaChat step",
      note: "Effective upstream auth is still incomplete.",
    };
  }
  if (!setup.security_ready) {
    return {
      href: "/admin/setup-security",
      label: "Open security step",
      note: "Close bootstrap exposure and stage gateway auth.",
    };
  }
  return {
    href: "/admin/playground",
    label: "Open playground",
    note: "Bootstrap-critical setup is complete. Run a smoke request next.",
  };
}
