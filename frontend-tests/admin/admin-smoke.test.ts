import assert from "node:assert/strict";
import test from "node:test";

import { createAdminSmokeHarness } from "./helpers/admin-smoke-harness.js";

const RUNTIME_PAYLOAD = {
  app_version: "1.0.0rc3",
  mode: "DEV",
  gigachat_api_mode: "SDK",
  gigachat_model: "GigaChat-Test",
  runtime_store_backend: "memory",
};

const SETUP_PAYLOAD = {
  bootstrap: { required: false },
  gigachat_ready: true,
  persistence_enabled: true,
  persisted: true,
  security_ready: true,
};

test("playground smoke renders the live page and updates request preview when presets change", async () => {
  const harness = createAdminSmokeHarness({
    path: "/admin/playground",
    routes: {
      "GET /admin/api/runtime": { json: RUNTIME_PAYLOAD },
      "GET /admin/api/setup": { json: SETUP_PAYLOAD },
    },
  });

  try {
    await harness.app.render();

    assert.equal(
      harness.document.getElementById("page-title")?.textContent?.trim(),
      "Manual request playground",
    );
    assert.match(harness.pageContent.textContent ?? "", /Run one smoke request/);

    const requestSummary = harness.document.getElementById("playground-request-summary");
    const requestBody = harness.document.getElementById("playground-request-body");
    assert.ok(requestSummary);
    assert.ok(requestBody);
    assert.match(requestSummary.textContent ?? "", /POST \/v1\/chat\/completions/);

    const presetButton = harness.document.querySelector<HTMLButtonElement>(
      '[data-preset="gemini-stream"]',
    );
    assert.ok(presetButton);

    presetButton.click();

    await harness.waitFor(
      () =>
        (requestSummary?.textContent ?? "").includes(
          "POST /v1beta/models/GigaChat-Test:streamGenerateContent?alt=sse",
        ),
      "Gemini preset preview",
    );

    assert.match(
      requestSummary?.textContent ?? "",
      /Authorization: Bearer \+ x-goog-api-key/,
    );
    assert.match(requestBody?.textContent ?? "", /"contents"/);
    assert.doesNotMatch(requestBody?.textContent ?? "", /"messages"/);
  } finally {
    harness.cleanup();
  }
});

test("files and batches smoke keeps SPA navigation working between hub and files page", async () => {
  const harness = createAdminSmokeHarness({
    path: "/admin/files-batches",
    routes: {
      "GET /admin/api/runtime": { json: RUNTIME_PAYLOAD },
      "GET /admin/api/setup": { json: SETUP_PAYLOAD },
      "GET /admin/api/files-batches/inventory": {
        json: {
          files: [
            {
              bytes: 128,
              filename: "request.jsonl",
              id: "file-1",
              purpose: "batch",
            },
          ],
          batches: [
            {
              endpoint: "/v1/chat/completions",
              id: "batch-1",
              input_file_id: "file-1",
              output_file_id: "file-out-1",
              status: "completed",
            },
          ],
          counts: {
            batches: 1,
            files: 1,
            needs_attention: 0,
            output_ready: 1,
          },
        },
      },
    },
  });

  try {
    await harness.app.render();

    assert.equal(
      harness.document.getElementById("page-title")?.textContent?.trim(),
      "Files and batch workbench",
    );
    assert.match(harness.pageContent.textContent ?? "", /Shared workbench hub/);
    assert.match(harness.pageContent.textContent ?? "", /request\.jsonl/);

    const openFilesLink = Array.from(
      harness.document.querySelectorAll<HTMLAnchorElement>('a[href="/admin/files"]'),
    ).find((link) => link.textContent?.includes("Open files"));
    assert.ok(openFilesLink);

    openFilesLink.dispatchEvent(
      new harness.window.MouseEvent("click", {
        bubbles: true,
        button: 0,
        cancelable: true,
      }),
    );

    await harness.waitFor(
      () =>
        harness.window.location.pathname === "/admin/files" &&
        harness.document.getElementById("page-title")?.textContent?.trim() ===
          "Files workbench",
      "files page navigation",
    );

    assert.match(
      harness.pageContent.textContent ?? "",
      /Upload one artifact, inspect metadata, then preview content\./,
    );
    assert.match(harness.pageContent.textContent ?? "", /Files shown/);
    assert.match(harness.pageContent.textContent ?? "", /request\.jsonl/);
  } finally {
    harness.cleanup();
  }
});

test("settings smoke renders the hub with revision history and focused section links", async () => {
  const harness = createAdminSmokeHarness({
    path: "/admin/settings",
    routes: {
      "GET /admin/api/runtime": { json: RUNTIME_PAYLOAD },
      "GET /admin/api/setup": { json: SETUP_PAYLOAD },
      "GET /admin/api/settings/application": {
        json: {
          control_plane: {
            persisted: true,
            persistence_enabled: true,
            updated_at: "2026-04-22T12:00:00Z",
          },
          values: {
            enabled_providers: ["gigachat"],
            mode: "DEV",
            runtime_store_active_backend: "memory",
            runtime_store_backend: "memory",
          },
        },
      },
      "GET /admin/api/settings/observability": {
        json: {
          values: {
            active_sinks: ["phoenix"],
            enable_telemetry: true,
            sinks: [{ enabled: true, id: "phoenix" }],
          },
        },
      },
      "GET /admin/api/settings/gigachat": {
        json: {
          values: {
            model: "GigaChat-Test",
            scope: "GIGACHAT_API_PERS",
          },
        },
      },
      "GET /admin/api/settings/security": {
        json: {
          values: {
            cors_allow_origins: ["http://localhost:3000"],
            enable_api_key_auth: true,
            logs_ip_allowlist: ["127.0.0.1"],
          },
        },
      },
      "GET /admin/api/settings/revisions?limit=6": {
        json: {
          revisions: [
            {
              sections: ["application", "security"],
              updated_at: "2026-04-22T11:30:00Z",
            },
          ],
        },
      },
    },
  });

  try {
    await harness.app.render();

    assert.equal(
      harness.document.getElementById("page-title")?.textContent?.trim(),
      "Settings hub",
    );
    assert.match(harness.pageContent.textContent ?? "", /Configuration map/);
    assert.match(harness.pageContent.textContent ?? "", /Latest revision:/);
    assert.match(harness.pageContent.textContent ?? "", /Observability/);
    assert.match(harness.pageContent.textContent ?? "", /Open history/);
  } finally {
    harness.cleanup();
  }
});
