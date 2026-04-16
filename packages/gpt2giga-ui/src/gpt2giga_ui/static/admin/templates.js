import { describePendingRuntimeImpact, planPendingApply, } from "./forms.js";
import { WORKFLOW_META, pathForPage } from "./routes.js";
import { escapeHtml, formatTimestamp, humanizeField, uniqueSortedStrings, } from "./utils.js";
export function banner(message, tone = "info") {
    const toneClass = tone === "danger" ? "banner banner--danger" : tone === "warn" ? "banner banner--warn" : "banner";
    return `<div class="${toneClass}">${escapeHtml(message)}</div>`;
}
export function pill(label, tone = "default") {
    const toneClass = tone === "good" ? "pill pill--good" : tone === "warn" ? "pill pill--warn" : "pill";
    return `<span class="${toneClass}">${escapeHtml(label)}</span>`;
}
export function card(title, body, className = "panel panel--span-4") {
    return `<article class="${className}"><div class="stack"><h3>${escapeHtml(title)}</h3>${body}</div></article>`;
}
export function kpi(label, value, className = "panel panel--span-3") {
    return `
    <article class="${className}">
      <div class="metric">
        <span class="metric__label">${escapeHtml(label)}</span>
        <span class="metric__value">${escapeHtml(value)}</span>
      </div>
    </article>
  `;
}
export function renderJson(data) {
    return `<pre class="code-block">${escapeHtml(JSON.stringify(data, null, 2))}</pre>`;
}
export function renderEmptyState(message) {
    return `<p class="muted">${escapeHtml(message)}</p>`;
}
export function renderDefinitionList(items, emptyMessage = "Nothing to show.") {
    if (!items.length) {
        return renderEmptyState(emptyMessage);
    }
    return `
    <dl class="definition-list">
      ${items
        .map((item) => `
            <div class="definition-list__row">
              <dt>${escapeHtml(item.label)}</dt>
              <dd>
                <strong>${escapeHtml(item.value)}</strong>
                ${item.note ? `<span class="muted">${escapeHtml(item.note)}</span>` : ""}
              </dd>
            </div>
          `)
        .join("")}
    </dl>
  `;
}
export function renderStatLines(items, emptyMessage = "Nothing to show.") {
    if (!items.length) {
        return renderEmptyState(emptyMessage);
    }
    return `
    <div class="stack">
      ${items
        .map((item) => {
        const tone = item.tone ?? "default";
        return `
            <div class="stat-line">
              <span class="muted">${escapeHtml(item.label)}</span>
              ${pill(item.value, tone)}
            </div>
          `;
    })
        .join("")}
    </div>
  `;
}
export function renderSecretField(options) {
    return `
    <div class="stack">
      <label class="field">
        <span>${escapeHtml(options.label)}</span>
        <textarea name="${escapeHtml(options.name)}" placeholder="${escapeHtml(options.placeholder)}"></textarea>
      </label>
      <p class="field-note">
        Stored preview: <strong>${escapeHtml(options.preview || "not configured")}</strong>.
        Leave blank to keep the current secret; paste a new value to replace it.
      </p>
      <label class="checkbox-field">
        <input name="${escapeHtml(options.clearControlName)}" type="checkbox" />
        <span>${escapeHtml(options.clearLabel)}</span>
      </label>
    </div>
  `;
}
export function renderFormSection(options) {
    const className = ["form-section", options.className].filter(Boolean).join(" ");
    return `
    <section class="${escapeHtml(className)}">
      <div class="form-section__header">
        <h4>${escapeHtml(options.title)}</h4>
        ${options.intro ? `<p class="muted">${escapeHtml(options.intro)}</p>` : ""}
      </div>
      ${options.body}
    </section>
  `;
}
export function renderTable(columns, rows, emptyMessage = "No rows available.") {
    if (!rows.length) {
        return renderEmptyState(emptyMessage);
    }
    return `
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            ${columns
        .map((column) => `<th${column.className ? ` class="${escapeHtml(column.className)}"` : ""}>${escapeHtml(column.label)}</th>`)
        .join("")}
          </tr>
        </thead>
        <tbody>
          ${rows
        .map((row) => `
                <tr>
                  ${row.map((cell) => `<td>${cell}</td>`).join("")}
                </tr>
              `)
        .join("")}
        </tbody>
      </table>
    </div>
  `;
}
export function renderSelectOption(value, selected, label) {
    const normalizedValue = String(value ?? "");
    return `<option value="${escapeHtml(normalizedValue)}" ${selected === normalizedValue ? "selected" : ""}>${escapeHtml(label ?? normalizedValue)}</option>`;
}
export function renderStaticSelectOptions(selected, values) {
    return values.map((value) => renderSelectOption(value, selected)).join("");
}
export function renderBooleanSelectOptions(selected) {
    const normalizedValue = selected ? "true" : "false";
    return [
        renderSelectOption("true", normalizedValue, "on"),
        renderSelectOption("false", normalizedValue, "off"),
    ].join("");
}
export function renderFilterSelectOptions(selected, values, emptyLabel = "All") {
    return [
        renderSelectOption("", selected, emptyLabel),
        ...uniqueSortedStrings(values).map((value) => renderSelectOption(value, selected)),
    ].join("");
}
export function renderSetupSteps(steps) {
    if (!steps.length) {
        return `<p class="muted">No setup steps reported.</p>`;
    }
    return `
    <div class="step-grid">
      ${steps
        .map((step) => `
            <article class="step-card ${step.ready ? "step-card--ready" : ""}">
              ${pill(step.ready ? "ready" : "pending", step.ready ? "good" : "warn")}
              <h4>${escapeHtml(step.label)}</h4>
              <p>${escapeHtml(step.description ?? "")}</p>
            </article>
          `)
        .join("")}
    </div>
  `;
}
export function renderWorkflowCard(options) {
    const workflow = WORKFLOW_META[options.workflow];
    return `
    <article class="workflow-card">
      <div class="workflow-card__header">
        <span class="eyebrow">${escapeHtml(workflow.label)}</span>
        <h4>${escapeHtml(options.title)}</h4>
        <p>${escapeHtml(options.note)}</p>
      </div>
      <div class="pill-row">${options.pills.join("")}</div>
      <div class="workflow-card__actions">
        ${options.actions
        .map((action) => `<a class="button${action.primary ? "" : " button--secondary"}" href="${escapeHtml(action.href)}">${escapeHtml(action.label)}</a>`)
        .join("")}
      </div>
    </article>
  `;
}
export function renderSubpageNav(options) {
    return `
    <div class="stack">
      <div class="stack">
        <span class="eyebrow">${escapeHtml(options.title)}</span>
        ${options.intro ? `<p class="muted">${escapeHtml(options.intro)}</p>` : ""}
      </div>
      <div class="toolbar">
        ${options.items
        .map((item) => {
        const active = item.page === options.currentPage;
        const href = options.hrefForPage?.(item.page) ?? pathForPage(item.page);
        return `
              <a
                class="button${active ? "" : " button--secondary"}"
                href="${escapeHtml(href)}"
                ${active ? 'aria-current="page"' : ""}
                title="${escapeHtml(item.description ?? item.label)}"
              >
                ${escapeHtml(item.label)}
              </a>
            `;
    })
        .join("")}
      </div>
    </div>
  `;
}
export function renderGuideLinks(links, intro = "Use these links when the current screen already narrowed the problem but you still need the longer operator playbook.") {
    if (!links.length) {
        return renderEmptyState("No guide links are configured.");
    }
    return `
    <div class="stack">
      <p class="muted">${escapeHtml(intro)}</p>
      <div class="step-grid">
        ${links
        .map((link) => `
              <article class="step-card">
                <h4>
                  <a href="${escapeHtml(link.href)}" target="_blank" rel="noreferrer noopener">
                    ${escapeHtml(link.label)}
                  </a>
                </h4>
                <p>${escapeHtml(link.note)}</p>
              </article>
            `)
        .join("")}
      </div>
    </div>
  `;
}
export function renderDiffTable(entries, emptyMessage = "No changes.") {
    if (!entries.length) {
        return `<p class="muted">${escapeHtml(emptyMessage)}</p>`;
    }
    return `
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Field</th>
            <th>Current</th>
            <th>Next</th>
          </tr>
        </thead>
        <tbody>
          ${entries
        .map((entry) => `
                <tr>
                  <td>${escapeHtml(humanizeField(entry.field))}</td>
                  <td>${formatDiffValue(entry.current)}</td>
                  <td>${formatDiffValue(entry.target)}</td>
                </tr>
              `)
        .join("")}
        </tbody>
      </table>
    </div>
  `;
}
export function renderDiffSections(diff, emptyMessage = "No changes.") {
    const sections = Object.entries(diff).filter(([, entries]) => entries.length > 0);
    if (!sections.length) {
        return `<p class="muted">${escapeHtml(emptyMessage)}</p>`;
    }
    return sections
        .map(([section, entries]) => `
        <div class="stack">
          ${pill(humanizeField(section))}
          ${renderDiffTable(entries)}
        </div>
      `)
        .join("");
}
export function renderFormChangeSummary(summary, options) {
    const idleMessage = options?.idleMessage ?? "No pending changes. This section matches the persisted runtime values.";
    const changeCount = summary.changedFields.length;
    const restartCount = summary.restartFields.length;
    const liveCount = summary.liveFields.length;
    const secretCount = summary.secretFields.length;
    const headline = changeCount === 0
        ? idleMessage
        : restartCount > 0 && liveCount > 0
            ? `${changeCount} pending field change${changeCount === 1 ? "" : "s"}. ${liveCount} apply live after save, while ${restartCount} still require a restart before mounted routes fully reflect them.`
            : restartCount > 0
                ? `${changeCount} pending field change${changeCount === 1 ? "" : "s"}. Save persists them now, but route posture still needs a restart before it fully matches the target state.`
                : `${changeCount} pending field change${changeCount === 1 ? "" : "s"}. This section can be persisted and applied without a restart.`;
    const previewFields = summary.changedFields.slice(0, 5);
    const remainingFields = summary.changedFields.length - previewFields.length;
    return `
    <div class="surface stack">
      ${options?.validationMessage ? banner(options.validationMessage, "danger") : ""}
      ${banner(headline, changeCount === 0 ? "info" : restartCount > 0 ? "warn" : "info")}
      <div class="pill-row">
        ${pill(changeCount === 0 ? "Status: clean" : `Changed fields: ${changeCount}`, changeCount === 0 ? "good" : "default")}
        ${restartCount > 0 ? pill(`Restart-sensitive: ${restartCount}`, "warn") : pill("Runtime apply: live", "good")}
        ${liveCount > 0 ? pill(`Live after save: ${liveCount}`, "good") : ""}
        ${secretCount > 0 ? pill(`Secrets touched: ${secretCount}`, "warn") : ""}
      </div>
      ${previewFields.length
        ? `
              <div class="pill-row">
                ${previewFields
            .map((field) => pill(humanizeField(field), summary.restartFields.includes(field) ? "warn" : "default"))
            .join("")}
                ${remainingFields > 0 ? pill(`+${remainingFields} more`) : ""}
              </div>
            `
        : ""}
      ${restartCount > 0
        ? renderPendingFieldGroup("Restart after save", summary.restartFields, "Mounted routes and runtime posture will not fully match these changes until the process restarts.", "warn")
        : ""}
      ${liveCount > 0
        ? renderPendingFieldGroup("Applies live", summary.liveFields, "These changes take effect as soon as the section is persisted.", "good")
        : ""}
      ${secretCount > 0
        ? renderPendingFieldGroup("Masked secret updates", summary.secretFields, "Secret values stay masked after save, but this shows which secret surfaces will rotate or clear.", "default")
        : ""}
      ${options?.note ? `<p class="muted">${escapeHtml(options.note)}</p>` : ""}
    </div>
  `;
}
export function renderControlPlaneSectionStatus({ summary, persisted, updatedAt, note, validationMessage, actionState, }) {
    const plannedApply = planPendingApply(summary);
    const runtimeImpact = describePendingRuntimeImpact(plannedApply);
    const persistedLabel = persisted && updatedAt
        ? `Persisted target: ${formatTimestamp(updatedAt)}`
        : "Persisted target: not saved yet";
    return `
    <div class="stack">
      ${actionState ? banner(actionState.message, actionState.tone) : ""}
      ${renderFormChangeSummary(plannedApply.effectiveSummary, {
        note,
        validationMessage,
    })}
      <div class="pill-row">
        ${pill(persistedLabel, persisted ? "default" : "warn")}
        ${pill(runtimeImpact.label, runtimeImpact.tone)}
        ${plannedApply.blockedLiveFields.length
        ? pill(`Live-capable if isolated: ${plannedApply.blockedLiveFields.length}`)
        : ""}
      </div>
      ${plannedApply.blockedLiveFields.length
        ? `<p class="muted">These fields can reload live on their own, but this save batch still waits for restart: ${escapeHtml(plannedApply.blockedLiveFields.map((field) => humanizeField(field)).join(", "))}.</p>`
        : ""}
      <p class="muted">${escapeHtml(runtimeImpact.detail)}</p>
    </div>
  `;
}
export function renderLoadingGrid() {
    return `
    <article class="panel panel--span-12">
      <div class="stack">
        <span class="eyebrow">Loading</span>
        <h3>Collecting console data…</h3>
        <p class="muted">The page is fetching runtime and control-plane state.</p>
      </div>
    </article>
  `;
}
function formatDiffValue(value) {
    if (value === null || value === undefined || value === "") {
        return '<span class="muted">empty</span>';
    }
    if (typeof value === "object") {
        return `<code>${escapeHtml(JSON.stringify(value))}</code>`;
    }
    return escapeHtml(String(value));
}
function renderPendingFieldGroup(label, fields, note, tone) {
    if (!fields.length) {
        return "";
    }
    return `
    <div class="change-group">
      <div class="change-group__header">
        <strong>${escapeHtml(label)}</strong>
        <span class="muted">${escapeHtml(note)}</span>
      </div>
      <div class="pill-row">
        ${fields.map((field) => pill(humanizeField(field), tone)).join("")}
      </div>
    </div>
  `;
}
