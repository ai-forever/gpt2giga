import { asArray, asRecord } from "../../utils.js";
export function buildSettingsPageState(currentPage, payloads) {
    return {
        activeSection: sectionForSettingsPage(currentPage),
        applicationValues: asRecord(payloads.application.values),
        controlPlaneStatus: asRecord(payloads.application.control_plane),
        currentPage,
        gigachatValues: asRecord(payloads.gigachat.values),
        observabilityValues: asRecord(payloads.observability.values),
        revisions: asArray(payloads.revisionsPayload.revisions),
        securityValues: asRecord(payloads.security.values),
    };
}
export function sectionForSettingsPage(page) {
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
