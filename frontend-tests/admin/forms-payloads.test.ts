import assert from "node:assert/strict";
import test from "node:test";

import { JSDOM } from "jsdom";

import {
  buildObservabilityPayload,
  collectGigachatPayload,
} from "../../gpt2giga/frontend/admin/forms-payloads.js";

function renderForm(markup: string): HTMLFormElement {
  const dom = new JSDOM(`<form>${markup}</form>`);
  return dom.window.document.querySelector("form") as HTMLFormElement;
}

test("buildObservabilityPayload groups nested settings and respects clear toggles", () => {
  const form = renderForm(`
    <select name="enable_telemetry">
      <option value="false">off</option>
      <option value="true" selected>on</option>
    </select>
    <input type="checkbox" name="sink_prometheus" />
    <input type="checkbox" name="sink_otlp" checked />
    <input type="checkbox" name="sink_langfuse" checked />
    <input type="checkbox" name="sink_phoenix" />
    <input name="otlp_traces_endpoint" value=" https://otlp.example/v1/traces " />
    <input name="otlp_service_name" value=" edge-proxy " />
    <input name="otlp_timeout_seconds" value="15" />
    <input name="otlp_max_pending_requests" value="200" />
    <textarea name="otlp_headers">{"authorization":"Bearer demo","x-tenant":17}</textarea>
    <input type="checkbox" name="otlp_clear_headers" />
    <input name="langfuse_base_url" value=" https://langfuse.example " />
    <textarea name="langfuse_public_key"></textarea>
    <input type="checkbox" name="langfuse_clear_public_key" checked />
    <textarea name="langfuse_secret_key">sk-demo</textarea>
    <input type="checkbox" name="langfuse_clear_secret_key" />
    <input name="phoenix_base_url" value="" />
    <input name="phoenix_project_name" value=" ops " />
    <textarea name="phoenix_api_key"></textarea>
    <input type="checkbox" name="phoenix_clear_api_key" checked />
  `);

  assert.deepEqual(buildObservabilityPayload(form), {
    enable_telemetry: true,
    active_sinks: ["otlp", "langfuse"],
    otlp: {
      traces_endpoint: "https://otlp.example/v1/traces",
      service_name: "edge-proxy",
      timeout_seconds: 15,
      max_pending_requests: 200,
      headers: {
        authorization: "Bearer demo",
        "x-tenant": "17",
      },
    },
    langfuse: {
      base_url: "https://langfuse.example",
      public_key: null,
      secret_key: "sk-demo",
    },
    phoenix: {
      base_url: null,
      project_name: "ops",
      api_key: null,
    },
  });
});

test("collectGigachatPayload trims optional text and preserves secret intents", () => {
  const form = renderForm(`
    <input name="model" value=" gigachat-pro " />
    <input name="scope" value="  " />
    <input name="user" value=" operator " />
    <input name="base_url" value=" https://gigachat.example " />
    <input name="auth_url" value="" />
    <input name="ca_bundle_file" value=" /certs/root.pem " />
    <textarea name="password">new-password</textarea>
    <input type="checkbox" name="clear_password" />
    <textarea name="credentials"></textarea>
    <input type="checkbox" name="clear_credentials" checked />
    <textarea name="access_token"></textarea>
    <input type="checkbox" name="clear_access_token" />
    <select name="verify_ssl_certs">
      <option value="false">off</option>
      <option value="true" selected>on</option>
    </select>
    <input name="timeout" value="45" />
  `);

  assert.deepEqual(collectGigachatPayload(form), {
    model: "gigachat-pro",
    scope: null,
    user: "operator",
    base_url: "https://gigachat.example",
    auth_url: null,
    ca_bundle_file: "/certs/root.pem",
    verify_ssl_certs: true,
    timeout: 45,
    password: "new-password",
    credentials: null,
  });
});
