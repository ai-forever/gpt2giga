import type { DiffEntry, SetupStep } from "./types";
import { escapeHtml, humanizeField } from "./utils";

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
