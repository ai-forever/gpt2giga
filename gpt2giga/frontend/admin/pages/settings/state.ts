import { asArray, asRecord } from "../../utils.js";
import type { SettingsPage, SettingsSection } from "./types.js";

export interface SettingsPageState {
  activeSection: SettingsSection | null;
  applicationValues: Record<string, unknown>;
  controlPlaneStatus: Record<string, unknown>;
  currentPage: SettingsPage;
  gigachatValues: Record<string, unknown>;
  observabilityValues: Record<string, unknown>;
  revisions: Record<string, unknown>[];
  securityValues: Record<string, unknown>;
}

export function buildSettingsPageState(
  currentPage: SettingsPage,
  payloads: {
    application: Record<string, unknown>;
    gigachat: Record<string, unknown>;
    observability: Record<string, unknown>;
    revisionsPayload: Record<string, unknown>;
    security: Record<string, unknown>;
  },
): SettingsPageState {
  return {
    activeSection: sectionForSettingsPage(currentPage),
    applicationValues: asRecord(payloads.application.values),
    controlPlaneStatus: asRecord(payloads.application.control_plane),
    currentPage,
    gigachatValues: asRecord(payloads.gigachat.values),
    observabilityValues: asRecord(payloads.observability.values),
    revisions: asArray<Record<string, unknown>>(payloads.revisionsPayload.revisions),
    securityValues: asRecord(payloads.security.values),
  };
}

export function sectionForSettingsPage(
  page: SettingsPage,
): SettingsSection | null {
  switch (page) {
    case "settings-application":
      return "application";
    case "settings-observability":
      return "observability";
    case "settings-gigachat":
      return "gigachat";
    case "settings-security":
      return "security";
    case "settings-history":
      return "history";
    default:
      return null;
  }
}
