import type { PendingChangeSummary } from "./types.js";

export const INVALID_JSON = "__invalid__";

export interface SecretFieldState {
  intent: "keep" | "replace" | "clear";
  message: string;
}

export interface PlannedApplyState {
  effectiveSummary: PendingChangeSummary;
  blockedLiveFields: string[];
}

export interface RuntimeImpactDescriptor {
  label: string;
  tone: "good" | "warn";
  detail: string;
}

export interface PersistOutcomeDescriptor {
  message: string;
  tone: "info" | "warn";
}

export type PendingDiffSection = "application" | "gigachat" | "security";
