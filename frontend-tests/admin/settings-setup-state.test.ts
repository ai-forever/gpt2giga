import assert from "node:assert/strict";
import test from "node:test";

import {
  buildSettingsPageState,
  sectionForSettingsPage,
} from "../../gpt2giga/frontend/admin/pages/settings/state.js";
import {
  buildSetupPageState,
  getNextRecommendedSetupPage,
  sectionForSetupPage,
} from "../../gpt2giga/frontend/admin/pages/setup/state.js";

test("buildSettingsPageState normalizes fetched payloads and resolves the active section", () => {
  const state = buildSettingsPageState("settings-observability", {
    application: {
      values: { mode: "DEV" },
      control_plane: { persisted: true, updated_at: "2026-04-22T10:00:00Z" },
    },
    observability: { values: { enable_telemetry: true } },
    gigachat: { values: { model: "GigaChat-2" } },
    security: { values: { enable_api_key_auth: true } },
    revisionsPayload: {
      revisions: [{ revision_id: "1" }],
    },
  });

  assert.equal(state.activeSection, "observability");
  assert.deepEqual(state.applicationValues, { mode: "DEV" });
  assert.deepEqual(state.controlPlaneStatus, {
    persisted: true,
    updated_at: "2026-04-22T10:00:00Z",
  });
  assert.deepEqual(state.revisions, [{ revision_id: "1" }]);
});

test("settings and setup section helpers map hub pages to null and focused pages to sections", () => {
  assert.equal(sectionForSettingsPage("settings"), null);
  assert.equal(sectionForSettingsPage("settings-history"), "history");
  assert.equal(sectionForSetupPage("setup"), null);
  assert.equal(sectionForSetupPage("setup-security"), "security");
});

test("getNextRecommendedSetupPage follows bootstrap order", () => {
  assert.deepEqual(
    getNextRecommendedSetupPage({
      claim: { required: true, claimed: false },
      persistence_enabled: true,
      persisted: false,
      gigachat_ready: false,
      security_ready: false,
    }),
    {
      href: "/admin/setup-claim",
      label: "Open claim step",
      note: "Claim the bootstrap session first.",
    },
  );

  assert.deepEqual(
    getNextRecommendedSetupPage({
      claim: { required: false, claimed: false },
      persistence_enabled: true,
      persisted: true,
      gigachat_ready: true,
      security_ready: false,
    }),
    {
      href: "/admin/setup-security",
      label: "Open security step",
      note: "Close bootstrap exposure and stage gateway auth.",
    },
  );

  assert.deepEqual(
    getNextRecommendedSetupPage({
      claim: { required: false, claimed: false },
      persistence_enabled: false,
      persisted: false,
      gigachat_ready: true,
      security_ready: true,
    }),
    {
      href: "/admin/playground",
      label: "Open playground",
      note: "Bootstrap-critical setup is complete. Run a smoke request next.",
    },
  );
});

test("buildSetupPageState normalizes nested setup payloads and carries the next step", () => {
  const state = buildSetupPageState("setup-security", {
    setup: {
      claim: { required: false, claimed: true },
      bootstrap: { required: false },
      warnings: ["gateway ready"],
      persisted: true,
      updated_at: "2026-04-22T10:00:00Z",
      persistence_enabled: true,
      gigachat_ready: true,
      security_ready: false,
    },
    runtime: { mode: "PROD" },
    application: { values: { enabled_providers: ["gigachat"] } },
    observability: { values: { active_sinks: ["otlp"] } },
    gigachat: { values: { model: "GigaChat-2-Max" } },
    security: { values: { enable_api_key_auth: true } },
    keys: {
      global: { configured: true },
      scoped: [{ name: "ops" }],
    },
  });

  assert.equal(state.activeSection, "security");
  assert.deepEqual(state.claim, { required: false, claimed: true });
  assert.deepEqual(state.bootstrap, { required: false });
  assert.equal(state.persisted, true);
  assert.deepEqual(state.globalKey, { configured: true });
  assert.deepEqual(state.scopedKeys, [{ name: "ops" }]);
  assert.deepEqual(state.nextStep, {
    href: "/admin/setup-security",
    label: "Open security step",
    note: "Close bootstrap exposure and stage gateway auth.",
  });
});
