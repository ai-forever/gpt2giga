import {
  describePendingRuntimeImpact,
  planPendingApply,
} from "./forms.js";
import { WORKFLOW_META, pathForPage } from "./routes.js";
import type { DiffEntry, PageId, PendingChangeSummary, SetupStep } from "./types.js";
import {
  escapeHtml,
  formatTimestamp,
  humanizeField,
  uniqueSortedStrings,
} from "./utils.js";

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

interface InlineStatus {
  tone: "info" | "warn" | "danger";
  message: string;
}

interface FormSectionOptions {
  body: string;
  className?: string;
  intro?: string;
  title: string;
}

interface WorkflowCardAction {
  label: string;
  href: string;
  primary?: boolean;
}

interface GuideLinkItem {
  href: string;
  label: string;
  note: string;
}

interface GuideLinksOptions {
  collapsibleSummary?: string;
  compact?: boolean;
  intro?: string;
}

interface SubpageNavLink {
  description?: string;
  label: string;
  page: PageId;
}

interface PageFrameOptions {
  className?: string;
  sections: string[];
  stats?: string[];
  toolbar?: string;
}

interface PageSectionOptions {
  actions?: string;
  body: string;
  bodyClassName?: string;
  className?: string;
  description?: string;
  eyebrow?: string;
  title: string;
  toolbar?: string;
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

export function renderPageFrame(options: PageFrameOptions): string {
  const className = ["page-frame", options.className].filter(Boolean).join(" ");
  return `
    <div class="${escapeHtml(className)}">
      ${
        options.stats?.length
          ? `
              <section class="page-frame__stats">
                ${options.stats.join("")}
              </section>
            `
          : ""
      }
      ${
        options.toolbar
          ? `
              <section class="page-toolbar">
                ${options.toolbar}
              </section>
            `
          : ""
      }
      ${options.sections.join("")}
    </div>
  `;
}

export function renderPageSection(options: PageSectionOptions): string {
  const className = ["page-section", options.className].filter(Boolean).join(" ");
  const bodyClassName = ["page-section__body", options.bodyClassName].filter(Boolean).join(" ");

  return `
    <section class="${escapeHtml(className)}">
      <div class="page-section__header">
        <div class="page-section__header-copy">
          ${options.eyebrow ? `<span class="eyebrow">${escapeHtml(options.eyebrow)}</span>` : ""}
          <h3 class="page-section__title">${escapeHtml(options.title)}</h3>
          ${options.description ? `<p class="muted">${escapeHtml(options.description)}</p>` : ""}
        </div>
        ${options.actions ? `<div class="page-section__header-actions">${options.actions}</div>` : ""}
      </div>
      ${options.toolbar ? `<div class="page-toolbar page-toolbar--section">${options.toolbar}</div>` : ""}
      <div class="${escapeHtml(bodyClassName)}">
        ${options.body}
      </div>
    </section>
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
        Stored: <strong>${escapeHtml(options.preview || "not configured")}</strong>. Blank keeps it; paste to replace.
      </p>
      <label class="checkbox-field">
        <input name="${escapeHtml(options.clearControlName)}" type="checkbox" />
        <span>${escapeHtml(options.clearLabel)}</span>
      </label>
    </div>
  `;
}

export function renderFormSection(options: FormSectionOptions): string {
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

export function renderSelectOption(value: unknown, selected: string, label?: string): string {
  const normalizedValue = String(value ?? "");
  return `<option value="${escapeHtml(normalizedValue)}" ${selected === normalizedValue ? "selected" : ""}>${escapeHtml(label ?? normalizedValue)}</option>`;
}

export function renderStaticSelectOptions(selected: string, values: unknown[]): string {
  return values.map((value) => renderSelectOption(value, selected)).join("");
}

export function renderBooleanSelectOptions(selected: boolean): string {
  const normalizedValue = selected ? "true" : "false";
  return [
    renderSelectOption("true", normalizedValue, "on"),
    renderSelectOption("false", normalizedValue, "off"),
  ].join("");
}

export function renderFilterSelectOptions(
  selected: string,
  values: unknown[],
  emptyLabel = "All",
): string {
  return [
    renderSelectOption("", selected, emptyLabel),
    ...uniqueSortedStrings(values).map((value) => renderSelectOption(value, selected)),
  ].join("");
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

export function renderWorkflowCard(options: {
  workflow: "start" | "configure" | "observe" | "diagnose";
  compact?: boolean;
  title: string;
  note?: string;
  pills: string[];
  actions: WorkflowCardAction[];
}): string {
  const workflow = WORKFLOW_META[options.workflow];
  const className = [
    "workflow-card",
    `workflow-card--${options.workflow}`,
    options.compact ? "workflow-card--compact" : "",
  ]
    .filter(Boolean)
    .join(" ");
  return `
    <article class="${className}">
      <div class="workflow-card__header">
        ${options.compact ? "" : `<span class="eyebrow">${escapeHtml(workflow.label)}</span>`}
        <h4>${escapeHtml(options.title)}</h4>
        ${options.note ? `<p>${escapeHtml(options.note)}</p>` : ""}
      </div>
      <div class="pill-row">${options.pills.join("")}</div>
      <div class="workflow-card__actions">
        ${options.actions
          .map(
            (action) =>
              `<a class="button${action.primary ? "" : " button--secondary"}" href="${escapeHtml(action.href)}">${escapeHtml(action.label)}</a>`,
          )
          .join("")}
      </div>
    </article>
  `;
}

export function renderSubpageNav(options: {
  currentPage: PageId;
  hrefForPage?: (page: PageId) => string;
  intro?: string;
  items: SubpageNavLink[];
  title: string;
}): string {
  const navLabel = `${options.title} pages`;
  return `
    <nav class="subpage-nav stack" aria-label="${escapeHtml(navLabel)}">
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
    </nav>
  `;
}

export function renderGuideLinks(
  links: GuideLinkItem[],
  options:
    | string
    | GuideLinksOptions = "Use these links when the current screen already narrowed the problem but you still need the longer operator playbook.",
): string {
  if (!links.length) {
    return renderEmptyState("No guide links are configured.");
  }

  const normalizedOptions: GuideLinksOptions =
    typeof options === "string" ? { intro: options } : options;
  const className = ["stack", "guide-links", normalizedOptions.compact ? "guide-links--compact" : ""]
    .filter(Boolean)
    .join(" ");
  const body = `
    <div class="${className}">
      ${normalizedOptions.intro ? `<p class="muted">${escapeHtml(normalizedOptions.intro)}</p>` : ""}
      <div class="step-grid">
        ${links
          .map(
            (link) => `
              <article class="step-card${normalizedOptions.compact ? " step-card--compact" : ""}">
                <h4>
                  <a href="${escapeHtml(link.href)}" target="_blank" rel="noreferrer noopener">
                    ${escapeHtml(link.label)}
                  </a>
                </h4>
                <p>${escapeHtml(link.note)}</p>
              </article>
            `,
          )
          .join("")}
      </div>
    </div>
  `;

  if (normalizedOptions.collapsibleSummary) {
    return `
      <details class="details-disclosure">
        <summary>${escapeHtml(normalizedOptions.collapsibleSummary)}</summary>
        ${body}
      </details>
    `;
  }

  return `
    ${body}
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
  const liveCount = summary.liveFields.length;
  const secretCount = summary.secretFields.length;

  const headline =
    changeCount === 0
      ? idleMessage
      : restartCount > 0 && liveCount > 0
        ? `${changeCount} pending field change${changeCount === 1 ? "" : "s"}. ${liveCount} apply live after save; ${restartCount} wait for restart.`
        : restartCount > 0
          ? `${changeCount} pending field change${changeCount === 1 ? "" : "s"}. Save persists them now; runtime catches up after restart.`
          : `${changeCount} pending field change${changeCount === 1 ? "" : "s"}. This section applies live after save.`;

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
      ${
        restartCount > 0
          ? renderPendingFieldGroup(
              "Restart after save",
              summary.restartFields,
              "Runtime posture does not fully match until restart.",
              "warn",
            )
          : ""
      }
      ${
        liveCount > 0
          ? renderPendingFieldGroup(
              "Applies live",
              summary.liveFields,
              "These changes take effect after save.",
              "good",
            )
          : ""
      }
      ${
        secretCount > 0
          ? renderPendingFieldGroup(
              "Masked secret updates",
              summary.secretFields,
              "Shows which stored secret surfaces rotate or clear.",
              "default",
            )
          : ""
      }
      ${options?.note ? `<p class="muted">${escapeHtml(options.note)}</p>` : ""}
    </div>
  `;
}

export function renderControlPlaneSectionStatus({
  summary,
  persisted,
  updatedAt,
  note,
  validationMessage,
  actionState,
}: {
  summary: PendingChangeSummary;
  persisted: boolean;
  updatedAt: unknown;
  note: string;
  validationMessage?: string;
  actionState?: InlineStatus | null;
}): string {
  const plannedApply = planPendingApply(summary);
  const runtimeImpact = describePendingRuntimeImpact(plannedApply);
  const persistedLabel =
    persisted && updatedAt
      ? `Saved target: ${formatTimestamp(updatedAt)}`
      : "Saved target: not saved yet";

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
        ${
          plannedApply.blockedLiveFields.length
            ? pill(`Live-capable if isolated: ${plannedApply.blockedLiveFields.length}`)
            : ""
        }
      </div>
      ${
        plannedApply.blockedLiveFields.length
          ? `<p class="muted">These fields apply live on their own, but this batch still waits for restart: ${escapeHtml(plannedApply.blockedLiveFields.map((field) => humanizeField(field)).join(", "))}.</p>`
          : ""
      }
      <p class="muted">${escapeHtml(runtimeImpact.detail)}</p>
    </div>
  `;
}

export function renderLoadingGrid(): string {
  return renderPageFrame({
    sections: [
      renderPageSection({
        eyebrow: "Loading",
        title: "Collecting console data…",
        description: "The page is fetching runtime and control-plane state.",
        body: "",
      }),
    ],
  });
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

function renderPendingFieldGroup(
  label: string,
  fields: string[],
  note: string,
  tone: "default" | "good" | "warn",
): string {
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
