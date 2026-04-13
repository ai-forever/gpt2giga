import type { DiffEntry, PendingChangeSummary, SetupStep } from "./types.js";
import { escapeHtml, humanizeField } from "./utils.js";

interface StatLineItem {
  label: string;
  value: string;
  tone?: "default" | "good" | "warn";
}

interface TableColumn {
  label: string;
  className?: string;
}

interface SecretFieldOptions {
  name: string;
  label: string;
  placeholder: string;
  preview: string;
  clearControlName: string;
  clearLabel: string;
}

interface DefinitionItem {
  label: string;
  value: string;
  note?: string;
}

export function banner(message: string, tone: "info" | "warn" | "danger" = "info"): string {
  const toneClass =
    tone === "danger" ? "banner banner--danger" : tone === "warn" ? "banner banner--warn" : "banner";
  return `<div class="${toneClass}">${escapeHtml(message)}</div>`;
}

export function pill(label: string, tone: "default" | "good" | "warn" = "default"): string {
  const toneClass =
    tone === "good" ? "pill pill--good" : tone === "warn" ? "pill pill--warn" : "pill";
  return `<span class="${toneClass}">${escapeHtml(label)}</span>`;
}

export function card(title: string, body: string, className = "panel panel--span-4"): string {
  return `<article class="${className}"><div class="stack"><h3>${escapeHtml(title)}</h3>${body}</div></article>`;
}

export function kpi(label: string, value: string | number, className = "panel panel--span-3"): string {
  return `
    <article class="${className}">
      <div class="metric">
        <span class="metric__label">${escapeHtml(label)}</span>
        <span class="metric__value">${escapeHtml(value)}</span>
      </div>
    </article>
  `;
}

export function renderJson(data: unknown): string {
  return `<pre class="code-block">${escapeHtml(JSON.stringify(data, null, 2))}</pre>`;
}

export function renderEmptyState(message: string): string {
  return `<p class="muted">${escapeHtml(message)}</p>`;
}

export function renderDefinitionList(
  items: DefinitionItem[],
  emptyMessage = "Nothing to show.",
): string {
  if (!items.length) {
    return renderEmptyState(emptyMessage);
  }

  return `
    <dl class="definition-list">
      ${items
        .map(
          (item) => `
            <div class="definition-list__row">
              <dt>${escapeHtml(item.label)}</dt>
              <dd>
                <strong>${escapeHtml(item.value)}</strong>
                ${item.note ? `<span class="muted">${escapeHtml(item.note)}</span>` : ""}
              </dd>
            </div>
          `,
        )
        .join("")}
    </dl>
  `;
}

export function renderStatLines(items: StatLineItem[], emptyMessage = "Nothing to show."): string {
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

export function renderSecretField(options: SecretFieldOptions): string {
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

export function renderTable(
  columns: TableColumn[],
  rows: string[][],
  emptyMessage = "No rows available.",
): string {
  if (!rows.length) {
    return renderEmptyState(emptyMessage);
  }

  return `
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            ${columns
              .map(
                (column) =>
                  `<th${column.className ? ` class="${escapeHtml(column.className)}"` : ""}>${escapeHtml(column.label)}</th>`,
              )
              .join("")}
          </tr>
        </thead>
        <tbody>
          ${rows
            .map(
              (row) => `
                <tr>
                  ${row.map((cell) => `<td>${cell}</td>`).join("")}
                </tr>
              `,
            )
            .join("")}
        </tbody>
      </table>
    </div>
  `;
}

export function renderSetupSteps(steps: SetupStep[]): string {
  if (!steps.length) {
    return `<p class="muted">No setup steps reported.</p>`;
  }
  return `
    <div class="step-grid">
      ${steps
        .map(
          (step) => `
            <article class="step-card ${step.ready ? "step-card--ready" : ""}">
              ${pill(step.ready ? "ready" : "pending", step.ready ? "good" : "warn")}
              <h4>${escapeHtml(step.label)}</h4>
              <p>${escapeHtml(step.description ?? "")}</p>
            </article>
          `,
        )
        .join("")}
    </div>
  `;
}

export function renderDiffTable(entries: DiffEntry[], emptyMessage = "No changes."): string {
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
            .map(
              (entry) => `
                <tr>
                  <td>${escapeHtml(humanizeField(entry.field))}</td>
                  <td>${formatDiffValue(entry.current)}</td>
                  <td>${formatDiffValue(entry.target)}</td>
                </tr>
              `,
            )
            .join("")}
        </tbody>
      </table>
    </div>
  `;
}

export function renderDiffSections(
  diff: Record<string, DiffEntry[]>,
  emptyMessage = "No changes.",
): string {
  const sections = Object.entries(diff).filter(([, entries]) => entries.length > 0);
  if (!sections.length) {
    return `<p class="muted">${escapeHtml(emptyMessage)}</p>`;
  }

  return sections
    .map(
      ([section, entries]) => `
        <div class="stack">
          ${pill(humanizeField(section))}
          ${renderDiffTable(entries)}
        </div>
      `,
    )
    .join("");
}

export function renderFormChangeSummary(
  summary: PendingChangeSummary,
  options?: {
    idleMessage?: string;
    note?: string;
    validationMessage?: string;
  },
): string {
  const idleMessage =
    options?.idleMessage ?? "No pending changes. This section matches the persisted runtime values.";
  const changeCount = summary.changedFields.length;
  const restartCount = summary.restartFields.length;
  const secretCount = summary.secretFields.length;

  const headline =
    changeCount === 0
      ? idleMessage
      : restartCount > 0
        ? `${changeCount} pending field change${changeCount === 1 ? "" : "s"}. ${restartCount} change${restartCount === 1 ? "" : "s"} require a restart before mounted routes fully reflect them.`
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
        ${secretCount > 0 ? pill(`Secrets touched: ${secretCount}`, "warn") : ""}
      </div>
      ${
        previewFields.length
          ? `
              <div class="pill-row">
                ${previewFields
                  .map((field) =>
                    pill(
                      humanizeField(field),
                      summary.restartFields.includes(field) ? "warn" : "default",
                    ),
                  )
                  .join("")}
                ${remainingFields > 0 ? pill(`+${remainingFields} more`) : ""}
              </div>
            `
          : ""
      }
      ${options?.note ? `<p class="muted">${escapeHtml(options.note)}</p>` : ""}
    </div>
  `;
}

export function renderLoadingGrid(): string {
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

function formatDiffValue(value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return '<span class="muted">empty</span>';
  }
  if (typeof value === "object") {
    return `<code>${escapeHtml(JSON.stringify(value))}</code>`;
  }
  return escapeHtml(String(value));
}
