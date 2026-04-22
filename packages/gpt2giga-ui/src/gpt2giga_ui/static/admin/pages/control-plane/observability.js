import { bindReplaceableFieldBehavior, bindSecretFieldBehavior, } from "../../forms.js";
import { pathForPage } from "../../routes.js";
import { banner, pill, renderBooleanSelectOptions, renderFormSection, renderSecretField, } from "../../templates.js";
import { asArray, asRecord, escapeHtml } from "../../utils.js";
import { OBSERVABILITY_PRESETS, } from "./types.js";
export function renderObservabilitySection(options) {
    const sinkCards = asArray(options.values.sinks);
    const sinkById = new Map(sinkCards
        .map((sink) => [String(sink.id ?? ""), sink])
        .filter(([id]) => Boolean(id)));
    const activeSinks = asArray(options.values.active_sinks);
    const otlp = asRecord(options.values.otlp);
    const langfuse = asRecord(options.values.langfuse);
    const phoenix = asRecord(options.values.phoenix);
    return `
    <form id="${escapeHtml(options.formId)}" class="form-shell">
      <div class="form-shell__intro">
        <div class="banner">${escapeHtml(options.bannerMessage)}</div>
        <div id="${escapeHtml(options.statusId)}"></div>
      </div>
      ${renderFormSection({
        title: "Telemetry gate and active sinks",
        intro: "Start with the pipeline switch and sink posture.",
        body: `
          <div class="dual-grid">
            <label class="field">
              <span>Telemetry pipeline</span>
              <select name="enable_telemetry">
                ${renderBooleanSelectOptions(Boolean(options.values.enable_telemetry))}
              </select>
            </label>
            <div class="stack">
              ${pill(`Active sinks: ${activeSinks.length || 0}`, activeSinks.length ? "good" : "warn")}
              ${pill(Boolean(options.values.metrics_enabled) ? "Metrics endpoint: live" : "Metrics endpoint: disabled", Boolean(options.values.metrics_enabled) ? "good" : "warn")}
              <p class="muted">Telemetry gates all exports.</p>
            </div>
          </div>
        `,
    })}
      ${renderFormSection({
        title: "Repo-local presets",
        intro: "Use presets to stage local compose defaults.",
        body: `
          <div class="banner">Each preset stages one local sink without touching the others.</div>
          <div class="workflow-grid">
            ${OBSERVABILITY_PRESETS.map((preset) => renderObservabilityPresetCard(preset)).join("")}
          </div>
        `,
    })}
      ${renderFormSection({
        title: "Sink-specific configuration",
        intro: "Keep raw endpoints and credentials in the sink cards.",
        body: `
          <div class="stack">
            ${renderObservabilitySinkCard({
            sink: sinkById.get("prometheus"),
            title: "Prometheus",
            description: "Built-in metrics endpoints.",
            body: `
                <label class="checkbox-field">
                  <input name="sink_prometheus" type="checkbox" ${activeSinks.includes("prometheus") ? "checked" : ""} />
                  <span>Enable Prometheus metrics sink</span>
                </label>
                <div class="dual-grid">
                  <div class="stack">
                    ${pill("Gateway: /metrics")}
                    ${pill("Admin: /admin/api/metrics")}
                  </div>
                  <p class="muted">No extra credentials.</p>
                </div>
              `,
        })}
            ${renderObservabilitySinkCard({
            sink: sinkById.get("otlp"),
            title: "OTLP / HTTP",
            description: "Send traces to an OTLP/HTTP endpoint.",
            body: `
                <label class="checkbox-field">
                  <input name="sink_otlp" type="checkbox" ${activeSinks.includes("otlp") ? "checked" : ""} />
                  <span>Enable OTLP sink</span>
                </label>
                <div class="dual-grid">
                  <label class="field">
                    <span>Traces endpoint</span>
                    <input name="otlp_traces_endpoint" placeholder="http://otel-collector:4318/v1/traces" value="${escapeHtml(otlp.traces_endpoint ?? "")}" />
                  </label>
                  <label class="field">
                    <span>Service name</span>
                    <input name="otlp_service_name" placeholder="gpt2giga" value="${escapeHtml(otlp.service_name ?? "")}" />
                  </label>
                </div>
                <div class="dual-grid">
                  <label class="field">
                    <span>Timeout seconds</span>
                    <input name="otlp_timeout_seconds" type="number" min="1" step="0.5" value="${escapeHtml(otlp.timeout_seconds ?? "")}" />
                  </label>
                  <label class="field">
                    <span>Max pending requests</span>
                    <input name="otlp_max_pending_requests" type="number" min="1" step="1" value="${escapeHtml(otlp.max_pending_requests ?? "")}" />
                  </label>
                </div>
                <div class="stack">
                  <label class="field">
                    <span>Headers override (JSON object)</span>
                    <textarea name="otlp_headers" placeholder='{"x-tenant":"demo","authorization":"Bearer ..."}'></textarea>
                  </label>
                  <p class="field-note">Stored: <strong>${escapeHtml(describeOtlpHeaderPreview(otlp))}</strong>. Blank keeps it; paste JSON to replace.</p>
                  <label class="checkbox-field">
                    <input name="otlp_clear_headers" type="checkbox" />
                    <span>Clear stored OTLP headers on save</span>
                  </label>
                </div>
              `,
        })}
            ${renderObservabilitySinkCard({
            sink: sinkById.get("langfuse"),
            title: "Langfuse",
            description: "Forward traces to Langfuse.",
            body: `
                <label class="checkbox-field">
                  <input name="sink_langfuse" type="checkbox" ${activeSinks.includes("langfuse") ? "checked" : ""} />
                  <span>Enable Langfuse sink</span>
                </label>
                <label class="field">
                  <span>Base URL</span>
                  <input name="langfuse_base_url" placeholder="https://cloud.langfuse.com" value="${escapeHtml(langfuse.base_url ?? "")}" />
                </label>
                <div class="dual-grid">
                  ${renderSecretField({
                name: "langfuse_public_key",
                label: "Public key",
                placeholder: "Paste a new Langfuse public key to replace the stored value",
                preview: String(langfuse.public_key_preview ?? "not configured"),
                clearControlName: "langfuse_clear_public_key",
                clearLabel: "Clear stored public key on save",
            })}
                  ${renderSecretField({
                name: "langfuse_secret_key",
                label: "Secret key",
                placeholder: "Paste a new Langfuse secret key to replace the stored value",
                preview: String(langfuse.secret_key_preview ?? "not configured"),
                clearControlName: "langfuse_clear_secret_key",
                clearLabel: "Clear stored secret key on save",
            })}
                </div>
              `,
        })}
            ${renderObservabilitySinkCard({
            sink: sinkById.get("phoenix"),
            title: "Phoenix",
            description: "Push traces to Phoenix.",
            body: `
                <label class="checkbox-field">
                  <input name="sink_phoenix" type="checkbox" ${activeSinks.includes("phoenix") ? "checked" : ""} />
                  <span>Enable Phoenix sink</span>
                </label>
                <div class="dual-grid">
                  <label class="field">
                    <span>Base URL</span>
                    <input name="phoenix_base_url" placeholder="http://phoenix:6006" value="${escapeHtml(phoenix.base_url ?? "")}" />
                  </label>
                  <label class="field">
                    <span>Project name</span>
                    <input name="phoenix_project_name" placeholder="gpt2giga-local" value="${escapeHtml(phoenix.project_name ?? "")}" />
                  </label>
                </div>
                <div class="dual-grid">
                  ${renderSecretField({
                name: "phoenix_api_key",
                label: "API key",
                placeholder: "Paste a new Phoenix API key to replace the stored value",
                preview: String(phoenix.api_key_preview ?? "not configured"),
                clearControlName: "phoenix_clear_api_key",
                clearLabel: "Clear stored Phoenix API key on save",
            })}
                </div>
              `,
        })}
          </div>
        `,
    })}
      <div class="form-actions">
        <button class="button" type="submit">${escapeHtml(options.submitLabel)}</button>
      </div>
    </form>
  `;
}
export function bindObservabilitySecretFields(form, values) {
    if (!form) {
        return {
            syncOtlpHeadersField: () => null,
            syncLangfusePublicKey: () => null,
            syncLangfuseSecretKey: () => null,
            syncPhoenixApiKey: () => null,
        };
    }
    return {
        syncOtlpHeadersField: bindReplaceableFieldBehavior({
            form,
            fieldName: "otlp_headers",
            clearFieldName: "otlp_clear_headers",
            preview: describeOtlpHeaderPreview(asRecord(values.otlp)),
            clearPlaceholder: "Uncheck clear to paste a replacement header object",
            noteReplace: "replace the stored OTLP headers on save.",
            noteClear: "clear the stored OTLP headers on save.",
            noteKeep: "keep the stored OTLP headers unless you paste a replacement JSON object.",
            messageReplace: "A new OTLP headers object is staged and will replace the stored value on save.",
            messageClear: "Stored OTLP headers will be removed when this section is saved.",
            messageKeep: "Stored OTLP headers remain unchanged unless you paste a replacement JSON object.",
        }),
        syncLangfusePublicKey: bindSecretFieldBehavior({
            form,
            fieldName: "langfuse_public_key",
            clearFieldName: "langfuse_clear_public_key",
            preview: String(asRecord(values.langfuse).public_key_preview ?? "not configured"),
        }),
        syncLangfuseSecretKey: bindSecretFieldBehavior({
            form,
            fieldName: "langfuse_secret_key",
            clearFieldName: "langfuse_clear_secret_key",
            preview: String(asRecord(values.langfuse).secret_key_preview ?? "not configured"),
        }),
        syncPhoenixApiKey: bindSecretFieldBehavior({
            form,
            fieldName: "phoenix_api_key",
            clearFieldName: "phoenix_clear_api_key",
            preview: String(asRecord(values.phoenix).api_key_preview ?? "not configured"),
        }),
    };
}
export function bindObservabilityPresetButtons(form, options) {
    if (!form) {
        return;
    }
    const fields = form.elements;
    const buttons = Array.from(form.querySelectorAll("[data-observability-preset]"));
    if (!buttons.length) {
        return;
    }
    buttons.forEach((button) => {
        button.addEventListener("click", () => {
            const preset = OBSERVABILITY_PRESETS.find((item) => item.id === button.dataset.observabilityPreset);
            if (!preset) {
                return;
            }
            preset.apply(fields);
            options.setActionState({
                tone: "info",
                message: `${preset.statusMessage} Review the diff, then save.`,
            });
            options.refreshStatus();
        });
    });
}
export function renderSetupObservabilityHandoff(values) {
    const state = buildSetupObservabilityHandoffState(values);
    return `
    <div class="stack">
      <div class="pill-row">
        ${pill(`Telemetry: ${state.telemetryEnabled ? "enabled" : "disabled"}`, state.telemetryEnabled ? "good" : "warn")}
        ${pill(`Active sinks: ${state.activeSinkCount}`, state.activeSinkCount ? "good" : "warn")}
        ${pill(state.metricsEnabled ? "Metrics endpoint: live" : "Metrics endpoint: disabled", state.metricsEnabled ? "good" : "warn")}
      </div>
      ${state.summaries.map((summary) => banner(summary.message, summary.tone)).join("")}
      <p class="muted">Use settings for sink tuning.</p>
      <div class="toolbar">
        <a class="button button--secondary" href="${escapeHtml(pathForPage("settings-observability"))}">Open observability settings</a>
      </div>
    </div>
  `;
}
export function buildSetupObservabilityHandoffState(values) {
    const activeSinks = asArray(values.active_sinks);
    const sinkCards = asArray(values.sinks);
    const enabledSinks = sinkCards.filter((sink) => Boolean(sink.enabled));
    const summaries = enabledSinks.length
        ? enabledSinks.map((sink) => describeSetupObservabilitySink(sink))
        : [
            {
                message: "Observability is optional during bootstrap.",
                tone: "info",
            },
        ];
    return {
        activeSinkCount: activeSinks.length,
        metricsEnabled: Boolean(values.metrics_enabled),
        summaries,
        telemetryEnabled: Boolean(values.enable_telemetry),
    };
}
export function describeOtlpHeaderPreview(otlp) {
    if (Array.isArray(otlp.header_names) && otlp.header_names.length > 0) {
        return `configured (${otlp.header_names.join(", ")})`;
    }
    return Boolean(otlp.headers_configured) ? "configured" : "not configured";
}
function describeSetupObservabilitySink(sink) {
    const label = String(sink.label ?? sink.id ?? "Sink");
    const missingFields = asArray(sink.missing_fields);
    if (Boolean(sink.configured)) {
        return {
            message: `${label} is enabled and ready for live exports.`,
            tone: "info",
        };
    }
    if (missingFields.length) {
        return {
            message: `${label} is enabled but still missing: ${missingFields.join(", ")}.`,
            tone: "warn",
        };
    }
    return {
        message: `${label} is enabled but still incomplete.`,
        tone: "warn",
    };
}
function renderObservabilitySinkCard(options) {
    const sink = options.sink ?? {};
    const enabled = Boolean(sink.enabled);
    const configured = Boolean(sink.configured);
    const missingFields = asArray(sink.missing_fields);
    const liveApply = Boolean(sink.live_apply);
    const restartRequired = Boolean(sink.restart_required);
    const summary = enabled
        ? configured
            ? "Enabled and configured."
            : missingFields.length
                ? `Enabled, missing: ${missingFields.join(", ")}.`
                : "Enabled, incomplete."
        : "Disabled. Stored values remain until removed.";
    return `
    <article class="step-card ${enabled ? "step-card--ready" : ""}">
      <div class="stack">
        <div class="toolbar">
          <div class="stack">
            <h4>${escapeHtml(options.title)}</h4>
            <p class="muted">${escapeHtml(options.description)}</p>
          </div>
          <div class="stack">
            ${pill(enabled ? "enabled" : "disabled", enabled ? "good" : "warn")}
            ${pill(configured ? "configured" : "needs fields", configured ? "good" : "warn")}
          </div>
        </div>
        ${banner(summary, enabled && !configured ? "warn" : "info")}
        <div class="pill-row">
          ${pill(liveApply ? "Live apply" : "Requires restart", liveApply ? "good" : "warn")}
          ${restartRequired ? pill("Restart-sensitive", "warn") : pill("Restart-safe", "good")}
          ${missingFields.length ? pill(`Missing: ${missingFields.join(", ")}`, "warn") : pill("Required fields satisfied", "good")}
        </div>
        ${options.body}
      </div>
    </article>
  `;
}
function renderObservabilityPresetCard(preset) {
    return `
    <article class="workflow-card">
      <div class="workflow-card__header">
        <span class="eyebrow">Local preset</span>
        <h4>${escapeHtml(preset.label)}</h4>
        <p>${escapeHtml(preset.description)}</p>
      </div>
      <div class="pill-row">
        ${preset.pillLabels.map((label) => pill(label)).join("")}
      </div>
      <p class="muted">Overlay: <strong>${escapeHtml(preset.composeOverlay)}</strong>. ${escapeHtml(preset.note)}</p>
      <div class="workflow-card__actions">
        <button
          class="button button--secondary"
          type="button"
          data-observability-preset="${escapeHtml(preset.id)}"
        >
          Apply preset
        </button>
      </div>
    </article>
  `;
}
